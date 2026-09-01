import calendar
import hashlib
import hmac
import json
import logging
import uuid
from io import BytesIO
import gocardless_pro
import stripe
from rest_framework.exceptions import NotFound
from datetime import date, timedelta
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Value, CharField
from django.db.models.functions import Cast, Concat, LPad
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django_filters.rest_framework import DjangoFilterBackend
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)
from rest_framework import permissions, status, response
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import SearchFilter
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    ListAPIView,
    RetrieveAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from api.serializers.tenants import (
    PaymentMethodSerializer,
    RentPaymentSerializer,
    RentBalanceSummarySerializer,
    CardPaymentRequestSerializer,
    DirectDebitSetupRequestSerializer,
    DirectDebitCompleteRequestSerializer,
    DirectDebitPaymentRequestSerializer,
    LandlordRentPaymentCreateSerializer,
    CardPaymentSerializer,
    MaintenanceRequestSerializer,
    MaintenanceRequestCommentSerializer,
)
from apps.organisation.stripe_connect import (
    sync_account_status,
    sync_account_status_from_stripe,
)
from apps.property.models import Tenant, ComplianceAndCertification, Property
from apps.tenant.enums import (
    RentPaymentStatusChoices,
    PaymentProviderChoices,
    PaymentMethodTypeChoices,
    PaymentMethodStatusChoices,
    MaintenanceStatus,
)
from apps.tenant.gocardless_client import (
    create_redirect_flow,
    complete_redirect_flow,
    create_payment as create_gocardless_payment,
    cancel_mandate,
)
from apps.tenant.models import (
    PaymentMethod,
    RentPayment,
    ProcessedWebhookEvent,
    CardPayment,
    MaintenanceRequest,
    MaintenanceRequestComment,
)
from apps.notification.tasks import (
    notify_maintenance_status_changed_task,
    notify_maintenance_request_created_task,
    notify_maintenance_comment_created_task,
    mark_comment_notifications_deleted_task,
)
from apps.tenant.stripe_client import create_payment_intent
from apps.tenant.utils import get_statement_date_range
from common.models import DocumentFile
from common.permission import IsTenant, IsLandlord, IsAdmin, IsLettingAgent
from api.serializers.property import (
    ComplianceAndCertificationSerializers,
    TenantSerializer,
)

logger = logging.getLogger("apps.tenant.payments")

_TERMINAL_STATUSES = {
    RentPaymentStatusChoices.CLEARED,
    RentPaymentStatusChoices.REFUNDED,
}


class PaymentMethodListCreateView(ListAPIView):
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsTenant]

    def get_queryset(self):
        return PaymentMethod.objects.filter(tenant=self.request.user)


class PaymentMethodDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = PaymentMethodSerializer
    permission_classes = [IsTenant]
    lookup_field = "alias"

    def get_queryset(self):
        return PaymentMethod.objects.filter(tenant=self.request.user)

    def perform_destroy(self, instance):
        if instance.provider == "GOCARDLESS" and instance.provider_mandate_id:
            try:
                cancel_mandate(instance.provider_mandate_id)
            except gocardless_pro.errors.GoCardlessProError:
                logger.exception(
                    "Failed to cancel GoCardless mandate on delete",
                    extra={"mandate_id": instance.provider_mandate_id},
                )
        instance.delete()


class RentPaymentListCreateView(ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsLandlord()]
        return [IsTenant()]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return LandlordRentPaymentCreateSerializer
        return RentPaymentSerializer

    def get_queryset(self):
        return RentPayment.objects.filter(tenant=self.request.user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def perform_create(self, serializer):
        tenant = serializer.validated_data["tenant"]
        serializer.save(
            tenant=tenant,
            property=tenant.property,
            organisation=tenant.property.organisation,
            status=RentPaymentStatusChoices.PENDING,
        )


class RentPaymentDetailView(RetrieveAPIView):
    serializer_class = RentPaymentSerializer
    permission_classes = [IsTenant]
    lookup_field = "alias"

    def get_queryset(self):
        return RentPayment.objects.filter(tenant=self.request.user)


class CardPaymentView(APIView):
    permission_classes = [IsTenant]

    def post(self, request):
        serializer = CardPaymentRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        print("RECEIVED AMOUNT:", serializer.validated_data["amount"])
        due_date = serializer.validated_data["due_date"]
        amount = serializer.validated_data["amount"]
        payment_method_id = serializer.validated_data.get("payment_method_id")

        if not payment_method_id:
            return Response(
                {"error": "payment_method_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant = request.user
        organisation = tenant.property.organisation

        if not organisation.stripe_charges_enabled:
            if organisation.stripe_account_id:
                try:
                    sync_account_status_from_stripe(organisation)
                    organisation.refresh_from_db()
                except stripe.error.StripeError:
                    logger.exception(
                        "CardPaymentView: failed to refresh Stripe account status",
                        extra={"organisation_id": organisation.id},
                    )

            if not organisation.stripe_charges_enabled:
                return Response(
                    {
                        "error": "Your landlord has not finished setting up payments yet. Please contact them."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        alias = uuid.uuid4()
        try:
            intent = create_payment_intent(
                amount=amount,
                payment_method_id=payment_method_id,
                idempotency_key=f"card-{alias}",
                metadata={
                    "tenant_id": str(request.user.id),
                    "due_date": str(due_date),
                    "organisation_id": str(organisation.id),
                },
                stripe_account_destination=organisation.stripe_account_id,
            )
        except stripe.error.CardError as e:
            logger.warning(
                "CardPaymentView: card declined",
                extra={
                    "tenant_id": request.user.id,
                    "due_date": str(due_date),
                    "stripe_error_code": e.code,
                    "stripe_error_message": str(e.user_message or e),
                },
            )
            CardPayment.objects.create(
                alias=alias,
                tenant=request.user,
                due_date=due_date,
                amount=amount,
                status=RentPaymentStatusChoices.FAILED,
                failure_reason=e.user_message or "Your card was declined.",
            )
            return Response(
                {"error": e.user_message or "Your card was declined."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except stripe.error.StripeError as e:
            logger.exception(
                "CardPaymentView: create_payment_intent failed",
                extra={
                    "tenant_id": request.user.id,
                    "due_date": str(due_date),
                    "payment_method_id": payment_method_id,
                    "stripe_error_type": type(e).__name__,
                },
            )
            CardPayment.objects.create(
                alias=alias,
                tenant=request.user,
                due_date=due_date,
                amount=amount,
                status=RentPaymentStatusChoices.FAILED,
                failure_reason="Payment provider error. Please try again.",
            )
            return Response(
                {"error": "Payment provider error. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payment_method_obj = self._get_or_create_card_payment_method(
            tenant=request.user, payment_method_id=payment_method_id
        )

        CardPayment.objects.create(
            alias=alias,
            tenant=request.user,
            due_date=due_date,
            amount=amount,
            provider_payment_id=intent.id,
            payment_method=payment_method_obj,
            status=RentPaymentStatusChoices.PROCESSING,
        )

        return Response(
            {"client_secret": intent.client_secret, "status": intent.status},
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _get_or_create_card_payment_method(tenant, payment_method_id):
        if not payment_method_id:
            return None

        existing = PaymentMethod.objects.filter(
            tenant=tenant,
            provider=PaymentProviderChoices.STRIPE,
            provider_payment_method_id=payment_method_id,
        ).first()
        if existing:
            return existing

        try:
            stripe_pm = stripe.PaymentMethod.retrieve(payment_method_id)
        except stripe.error.StripeError:
            logger.exception(
                "Failed to fetch Stripe PaymentMethod details",
                extra={"payment_method_id": payment_method_id},
            )
            return None

        card = getattr(stripe_pm, "card", None)

        return PaymentMethod.objects.create(
            tenant=tenant,
            provider=PaymentProviderChoices.STRIPE,
            method_type=PaymentMethodTypeChoices.CARD,
            provider_payment_method_id=payment_method_id,
            status=PaymentMethodStatusChoices.ACTIVE,
            is_default=False,
            card_last4=getattr(card, "last4", None) if card else None,
            card_brand=getattr(card, "brand", None) if card else None,
        )


class DirectDebitSetupView(APIView):
    permission_classes = [IsTenant]

    def post(self, request):
        serializer = DirectDebitSetupRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = request.user
        session_token = str(uuid.uuid4())

        try:
            flow = create_redirect_flow(
                tenant=tenant,
                session_token=session_token,
                success_redirect_url=serializer.validated_data["success_redirect_url"],
            )
        except gocardless_pro.errors.GoCardlessProError:
            logger.exception(
                "GoCardless create_redirect_flow failed", extra={"tenant_id": tenant.id}
            )
            return Response(
                {"error": "Payment provider error. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {"redirect_url": flow.redirect_url, "session_token": session_token},
            status=status.HTTP_201_CREATED,
        )


class DirectDebitCompleteView(APIView):
    permission_classes = [IsTenant]

    def post(self, request):
        serializer = DirectDebitCompleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = request.user

        try:
            flow = complete_redirect_flow(
                serializer.validated_data["redirect_flow_id"],
                serializer.validated_data["session_token"],
            )
        except gocardless_pro.errors.InvalidStateError:
            return Response(
                {
                    "error": "This direct debit setup link has expired or already been used."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except gocardless_pro.errors.GoCardlessProError:
            logger.exception(
                "GoCardless complete_redirect_flow failed",
                extra={"tenant_id": tenant.id},
            )
            return Response(
                {"error": "Payment provider error. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        with transaction.atomic():
            PaymentMethod.objects.select_for_update().filter(
                tenant=tenant, is_default=True
            ).update(is_default=False)

            payment_method = PaymentMethod.objects.create(
                tenant=tenant,
                provider="GOCARDLESS",
                method_type="DIRECT_DEBIT",
                provider_customer_id=flow.links.customer,
                provider_mandate_id=flow.links.mandate,
                status="ACTIVE",
                is_default=True,
            )

        return Response(
            PaymentMethodSerializer(payment_method).data,
            status=status.HTTP_201_CREATED,
        )


class DirectDebitPaymentView(APIView):
    permission_classes = [IsTenant]

    def post(self, request):
        serializer = DirectDebitPaymentRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        rent_payment = serializer.validated_data["rent_payment"]
        payment_method = serializer.validated_data["payment_method"]

        try:
            payment = create_gocardless_payment(
                mandate_id=payment_method.provider_mandate_id,
                amount=rent_payment.amount,
                idempotency_key=f"dd-{rent_payment.alias}",
                metadata={"rent_payment_alias": str(rent_payment.alias)},
            )
        except gocardless_pro.errors.InvalidStateError as e:
            return Response(
                {
                    "error": "Mandate is not active. Please set up direct debit again.",
                    "detail": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except gocardless_pro.errors.GoCardlessProError:
            return Response(
                {"error": "Payment provider error. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        updated = (
            RentPayment.objects.filter(pk=rent_payment.pk)
            .exclude(status__in=_TERMINAL_STATUSES)
            .update(
                provider_payment_id=payment.id,
                payment_method=payment_method,
                status=RentPaymentStatusChoices.PROCESSING,
            )
        )

        if not updated:
            logger.warning(
                "DirectDebitPaymentView: rent_payment already terminal, skipped status downgrade",
                extra={
                    "rent_payment_alias": str(rent_payment.alias),
                    "payment_id": payment.id,
                },
            )

        return Response(
            {"provider_payment_id": payment.id, "status": payment.status},
            status=status.HTTP_201_CREATED,
        )


class DirectDebitCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        redirect_flow_id = request.GET.get("redirect_flow_id")
        return Response({"redirect_flow_id": redirect_flow_id})


class RentBalanceSummaryView(APIView):
    permission_classes = [IsTenant]

    def get(self, request):
        serializer = RentBalanceSummarySerializer(request.user)
        return Response(serializer.data)


class RentStatementView(APIView):
    """
    api/rent-statements/?period=yearly&year=2026
    api/rent-statements/?period=monthly&year=2026&month=7
    api/rent-statements/?period=weekly&year=2026&week=29
    api/rent-statements/?period=custom&start_date=2026-01-01&end_date=2026-03-31
    """

    permission_classes = [IsTenant]

    def get(self, request):
        period = request.query_params.get("period", "yearly")

        try:
            start, end, label = get_statement_date_range(period, request.query_params)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        tenant = request.user

        rent_payments = RentPayment.objects.filter(
            tenant=tenant, due_date__gte=start, due_date__lte=end
        ).select_related("payment_method")
        card_payments = CardPayment.objects.filter(
            tenant=tenant, due_date__gte=start, due_date__lte=end
        ).select_related("payment_method")

        rows = self._build_rows(rent_payments, card_payments)

        buffer = self.build_rent_statement_pdf(tenant, rows, period_label=label)
        filename = f"rent_statement_{period}_{start}_{end}.pdf"
        return FileResponse(buffer, as_attachment=True, filename=filename)

    @staticmethod
    def _payment_type_label(payment_method, fallback):
        if payment_method is None:
            return fallback
        if payment_method.provider == PaymentProviderChoices.GOCARDLESS:
            return "GoCardless"
        if payment_method.provider == PaymentProviderChoices.STRIPE:
            return "Card"
        return payment_method.get_provider_display()

    @classmethod
    def _build_rows(cls, rent_payments, card_payments):
        """Merge RentPayment and CardPayment records into a single, date-sorted list of row dicts."""
        rows = []

        for p in rent_payments:
            rows.append(
                {
                    "date": p.paid_date or p.due_date,
                    "type": cls._payment_type_label(p.payment_method, "Rent"),
                    "amount": p.amount,
                    "status": p.get_status_display(),
                }
            )

        for c in card_payments:
            rows.append(
                {
                    "date": c.due_date,
                    "type": cls._payment_type_label(c.payment_method, "Card"),
                    "amount": c.amount,
                    "status": c.get_status_display(),
                }
            )

        rows.sort(key=lambda r: r["date"])
        return rows

    @staticmethod
    def build_rent_statement_pdf(tenant, rows, period_label):
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm
        )
        styles = getSampleStyleSheet()
        elements = []

        elements.append(Paragraph(f"Rent Statement — {period_label}", styles["Title"]))
        elements.append(Paragraph(f"Tenant: {tenant}", styles["Normal"]))
        elements.append(Spacer(1, 12))

        data = [["Date", "Type", "Amount", "Status"]]
        total = 0
        for r in rows:
            data.append(
                [
                    r["date"].strftime("%d %b %Y"),
                    r["type"],
                    f"£{r['amount']:,.2f}",
                    r["status"],
                ]
            )
            total += r["amount"]

        data.append(["", "", f"Total: £{total:,.2f}", ""])

        table = Table(data, colWidths=[100, 80, 120, 120])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -2), 0.5, colors.grey),
                    ("FONTNAME", (-2, -1), (-2, -1), "Helvetica-Bold"),
                    ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                ]
            )
        )
        elements.append(table)

        doc.build(elements)
        buffer.seek(0)
        return buffer


class WebhookRateThrottle(SimpleRateThrottle):
    scope = "webhook"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [WebhookRateThrottle]

    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            logger.warning("Stripe webhook signature verification failed")
            return Response(
                {"error": "Invalid payload or signature"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event_type = event["type"]
            data_object = event["data"]["object"]
        except (KeyError, TypeError):
            logger.warning(
                "Stripe webhook malformed payload", extra={"event_id": event.get("id")}
            )
            return Response(
                {"error": "Malformed event payload"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                if not self._claim_event(event["id"]):
                    return Response(
                        {"received": True, "duplicate": True}, status=status.HTTP_200_OK
                    )

                if event_type == "payment_intent.succeeded":
                    self._mark_payment(
                        data_object["id"], RentPaymentStatusChoices.CLEARED
                    )
                    self._mark_card_payment(
                        data_object["id"], RentPaymentStatusChoices.CLEARED
                    )
                elif event_type == "payment_intent.payment_failed":
                    reason = data_object.get("last_payment_error", {}).get(
                        "message", "Payment failed"
                    )
                    self._mark_payment(
                        data_object["id"],
                        RentPaymentStatusChoices.FAILED,
                        failure_reason=reason,
                    )
                    self._mark_card_payment(
                        data_object["id"],
                        RentPaymentStatusChoices.FAILED,
                        failure_reason=reason,
                    )
                elif event_type == "account.updated":
                    sync_account_status(
                        stripe_account_id=data_object["id"],
                        charges_enabled=data_object.get("charges_enabled", False),
                        payouts_enabled=data_object.get("payouts_enabled", False),
                        details_submitted=data_object.get("details_submitted", False),
                    )
        except Exception:
            logger.exception(
                "Stripe webhook processing failed", extra={"event_id": event.get("id")}
            )
            return Response(
                {"error": "Processing error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"received": True}, status=status.HTTP_200_OK)

    @staticmethod
    def _claim_event(event_id):
        try:
            ProcessedWebhookEvent.objects.create(provider="stripe", event_id=event_id)
            return True
        except IntegrityError:
            return False

    @staticmethod
    def _mark_payment(provider_payment_id, new_status, failure_reason=None):
        update_fields = {"status": new_status}
        if new_status == RentPaymentStatusChoices.CLEARED:
            update_fields["paid_date"] = timezone.localdate()
        if failure_reason:
            update_fields["failure_reason"] = failure_reason

        updated = (
            RentPayment.objects.filter(provider_payment_id=provider_payment_id)
            .exclude(status__in=_TERMINAL_STATUSES)
            .update(**update_fields)
        )

        if not updated:
            logger.warning(
                "Stripe webhook: no matching non-terminal RentPayment",
                extra={
                    "provider_payment_id": provider_payment_id,
                    "new_status": new_status,
                },
            )

    @staticmethod
    def _mark_card_payment(provider_payment_id, new_status, failure_reason=None):
        update_fields = {"status": new_status}
        if failure_reason:
            update_fields["failure_reason"] = failure_reason

        card_payment = (
            CardPayment.objects.filter(provider_payment_id=provider_payment_id)
            .exclude(status__in=_TERMINAL_STATUSES)
            .first()
        )

        if not card_payment:
            logger.warning(
                "Stripe webhook: no matching non-terminal CardPayment",
                extra={
                    "provider_payment_id": provider_payment_id,
                    "new_status": new_status,
                },
            )
            return

        CardPayment.objects.filter(pk=card_payment.pk).update(**update_fields)

        if new_status == RentPaymentStatusChoices.CLEARED:
            rent_update_fields = {**update_fields, "paid_date": timezone.localdate()}
        else:
            rent_update_fields = update_fields

        rent_updated = (
            RentPayment.objects.filter(
                tenant_id=card_payment.tenant_id,
                due_date=card_payment.due_date,
            )
            .exclude(status__in=_TERMINAL_STATUSES)
            .update(**rent_update_fields)
        )

        if not rent_updated:
            logger.warning(
                "Stripe webhook: no matching non-terminal RentPayment for card payment",
                extra={
                    "provider_payment_id": provider_payment_id,
                    "tenant_id": card_payment.tenant_id,
                    "due_date": str(card_payment.due_date),
                },
            )


@method_decorator(csrf_exempt, name="dispatch")
class GoCardlessWebhookView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [WebhookRateThrottle]

    def post(self, request):
        raw_body = request.body
        signature = request.META.get("HTTP_WEBHOOK_SIGNATURE", "")

        if not self._is_valid_signature(raw_body, signature):
            logger.warning("GoCardless webhook signature verification failed")
            return Response(
                {"error": "Invalid signature"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return Response(
                {"error": "Malformed JSON payload"}, status=status.HTTP_400_BAD_REQUEST
            )

        events = payload.get("events", [])

        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue

            try:
                with transaction.atomic():
                    if not self._claim_event(event_id):
                        continue

                    resource_type = event.get("resource_type")
                    action = event.get("action")
                    links = event.get("links", {})

                    if resource_type == "payments":
                        provider_payment_id = links.get("payment")

                        if action == "confirmed":
                            self._mark_payment(
                                provider_payment_id, RentPaymentStatusChoices.CLEARED
                            )
                        elif action == "failed":
                            self._mark_payment(
                                provider_payment_id,
                                RentPaymentStatusChoices.FAILED,
                                failure_reason="Direct debit payment failed",
                            )
            except Exception:
                logger.exception(
                    "GoCardless webhook event processing failed",
                    extra={"event_id": event_id},
                )
                continue

        return Response({"received": True}, status=status.HTTP_200_OK)

    @staticmethod
    def _claim_event(event_id):
        try:
            ProcessedWebhookEvent.objects.create(
                provider="gocardless", event_id=event_id
            )
            return True
        except IntegrityError:
            return False

    @staticmethod
    def _is_valid_signature(raw_body, signature):
        secret = settings.GOCARDLESS_WEBHOOK_SECRET.encode()
        computed = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, signature)

    @staticmethod
    def _mark_payment(provider_payment_id, new_status, failure_reason=None):
        if not provider_payment_id:
            return

        update_fields = {"status": new_status}
        if new_status == RentPaymentStatusChoices.CLEARED:
            update_fields["paid_date"] = timezone.localdate()
        if failure_reason:
            update_fields["failure_reason"] = failure_reason

        updated = (
            RentPayment.objects.filter(provider_payment_id=provider_payment_id)
            .exclude(status__in=_TERMINAL_STATUSES)
            .update(**update_fields)
        )

        if not updated:
            logger.warning(
                "GoCardless webhook: no matching non-terminal RentPayment",
                extra={
                    "provider_payment_id": provider_payment_id,
                    "new_status": new_status,
                },
            )


ENDING_SOON_DAYS = 30


class PropertyTenancyListView(APIView):
    permission_classes = [IsTenant]

    def get(self, request):
        today = date.today()
        tenants = Tenant.objects.select_related("property").filter(id=request.user.id)

        results = []
        for tenant in tenants:
            tenancy_term = None
            length = None
            status = "Inactive"

            if tenant.tenancy_start_date and tenant.tenancy_end_date:
                tenancy_term = (
                    f"{tenant.tenancy_start_date:%b %-d, %Y} - "
                    f"{tenant.tenancy_end_date:%b %-d, %Y}"
                )
                months = round(
                    (tenant.tenancy_end_date - tenant.tenancy_start_date).days / 30
                )
                length = f"{months}-month agreement"

                if tenant.tenancy_end_date < today:
                    status = "Expired"
                elif tenant.tenancy_end_date <= today + timedelta(
                    days=ENDING_SOON_DAYS
                ):
                    status = "Ending soon"
                elif tenant.tenancy_start_date <= today:
                    status = "Active"

            results.append(
                {
                    "tenant_id": tenant.id,
                    "property_address": tenant.property.address,
                    "tenancy_term": tenancy_term,
                    "length": length,
                    "status": status,
                }
            )

        return Response(results)


class FinancialOverviewListView(APIView):
    permission_classes = [IsTenant]

    def get(self, request):
        today = date.today()
        tenants = Tenant.objects.select_related("property").filter(id=request.user.id)

        results = []
        for tenant in tenants:
            payments = RentPayment.objects.filter(tenant=tenant).order_by("-due_date")[
                :10
            ]

            outstanding_balance = sum(
                p.amount for p in payments if p.status not in _TERMINAL_STATUSES
            )

            next_rent_due_date = None
            upcoming = (
                RentPayment.objects.filter(tenant=tenant, due_date__gte=today)
                .exclude(status__in=_TERMINAL_STATUSES)
                .order_by("due_date")
                .first()
            )
            if upcoming:
                next_rent_due_date = upcoming.due_date
            elif tenant.tenancy_start_date:
                rent_day = tenant.tenancy_start_date.day
                year, month = today.year, today.month
                last_day_this_month = calendar.monthrange(year, month)[1]
                due_this_month = date(year, month, min(rent_day, last_day_this_month))

                if due_this_month >= today:
                    next_rent_due_date = due_this_month
                else:
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                    last_day_next_month = calendar.monthrange(year, month)[1]
                    next_rent_due_date = date(
                        year, month, min(rent_day, last_day_next_month)
                    )

            results.append(
                {
                    "tenant_id": tenant.id,
                    "next_rent_due_date": next_rent_due_date,
                    "outstanding_balance": outstanding_balance,
                    "rent_amount": tenant.rent_amount,
                }
            )

        return Response(results)


class PaymentHistoryView(APIView):
    permission_classes = [IsTenant]

    def get(self, request):
        tenant = request.user
        card_payments = CardPayment.objects.filter(tenant=tenant).select_related(
            "payment_method"
        )

        gocardless_payments = RentPayment.objects.filter(
            tenant=tenant,
            payment_method__provider=PaymentProviderChoices.GOCARDLESS,
        ).select_related("payment_method")

        history = self._build_history(card_payments, gocardless_payments)
        history.sort(key=lambda r: r["created_at"], reverse=True)

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(history, request, view=self)
        return paginator.get_paginated_response(page)

    @staticmethod
    def _build_history(card_payments, gocardless_payments):
        rows = []
        for c in card_payments:
            rows.append(
                {
                    "alias": c.alias,
                    "payment_method": (
                        PaymentMethodSerializer(c.payment_method).data
                        if c.payment_method
                        else None
                    ),
                    "provider_payment_id": c.provider_payment_id,
                    "amount": c.amount,
                    "due_date": c.due_date,
                    "status": c.get_status_display(),
                    "failure_reason": c.failure_reason,
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                }
            )
        for p in gocardless_payments:
            rows.append(
                {
                    "alias": p.alias,
                    "payment_method": (
                        PaymentMethodSerializer(p.payment_method).data
                        if p.payment_method
                        else None
                    ),
                    "provider_payment_id": p.provider_payment_id,
                    "amount": p.amount,
                    "due_date": p.due_date,
                    "status": p.get_status_display(),
                    "failure_reason": p.failure_reason,
                    "created_at": p.created_at,
                    "updated_at": p.updated_at,
                }
            )
        return rows


class MaintenanceRequestListCreateAPIView(ListCreateAPIView):
    serializer_class = MaintenanceRequestSerializer
    filter_backends = [
        DjangoFilterBackend,
        SearchFilter,
    ]
    filterset_fields = {
        "is_emergency": ["exact"],
        "current_status": ["exact", "in"],
        "category": ["exact", "in"],
    }
    search_fields = [
        "request_id",
        "property__property_name",
        "property__company_name",
        "tenant__title",
        "tenant__first_name",
        "tenant__middle_name",
        "tenant__last_name",
        "tenant__email",
        "tenant__phone",
    ]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsTenant()]
        return [(IsTenant | IsLandlord | IsAdmin)()]

    def get_queryset(self):
        user = self.request.user
        if isinstance(user, Tenant):
            queryset = MaintenanceRequest.objects.filter(tenant=user)
        else:
            organisation = user.get_organisation()
            if organisation:
                queryset = MaintenanceRequest.objects.filter(organisation=organisation)
            else:
                return MaintenanceRequest.objects.none()

        return queryset.annotate(
            request_id=Concat(
                Value("#MR-"),
                LPad(Cast("id", CharField()), 8, Value("0")),
                output_field=CharField(),
            )
        )

    def perform_create(self, serializer):
        tenant = self.request.user
        maintenance_request = serializer.save(
            tenant=tenant,
            property=tenant.property,
            organisation=tenant.organisation,
        )

        files = self.request.FILES.getlist("documents")
        document_files = [DocumentFile.objects.create(file=file) for file in files]
        maintenance_request.documents.set(document_files)
        transaction.on_commit(
            lambda: notify_maintenance_request_created_task.delay(
                maintenance_request.id
            )
        )


class MaintenanceRequestRetrieveUpdateDestroyAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = MaintenanceRequestSerializer
    lookup_field = "alias"
    permission_classes = [IsTenant | IsLandlord | IsAdmin]

    def get_queryset(self):
        user = self.request.user
        if isinstance(user, Tenant):
            return MaintenanceRequest.objects.filter(tenant=user)

        organisation = user.get_organisation()
        if organisation:
            return MaintenanceRequest.objects.filter(organisation=organisation)

        return MaintenanceRequest.objects.none()

    def perform_update(self, serializer):
        previous_status = serializer.instance.current_status
        instance = serializer.save()
        if instance.current_status != previous_status:
            transaction.on_commit(
                lambda: notify_maintenance_status_changed_task.delay(
                    instance.id,
                    updated_by_id=self.request.user.id,
                )
            )


class MaintenanceRequestCommentListCreateView(ListCreateAPIView):
    serializer_class = MaintenanceRequestCommentSerializer
    permission_classes = [IsTenant | IsLandlord | IsAdmin | IsLettingAgent]
    pagination_class = None

    def get_maintenance_request(self):
        user = self.request.user
        if isinstance(user, Tenant):
            return get_object_or_404(
                MaintenanceRequest,
                alias=self.kwargs["maintenance_request_alias"],
                tenant=user,
            )
        organisation = user.get_organisation()
        if not organisation:
            raise PermissionDenied("You are not part of an organisation.")
        return get_object_or_404(
            MaintenanceRequest,
            alias=self.kwargs["maintenance_request_alias"],
            organisation=organisation,
        )

    def get_queryset(self):
        return (
            MaintenanceRequestComment.objects.filter(
                maintenance_request=self.get_maintenance_request(),
                parent__isnull=True,
            )
            .select_related("staff_author", "tenant_author")
            .prefetch_related("documents", "replies")
            .order_by("created_at")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["maintenance_request"] = self.get_maintenance_request()
        return context

    def perform_create(self, serializer):
        user = self.request.user
        maintenance_request = self.get_maintenance_request()
        if isinstance(user, Tenant):
            comment = serializer.save(
                tenant_author=user, maintenance_request=maintenance_request
            )
        else:
            comment = serializer.save(
                staff_author=user, maintenance_request=maintenance_request
            )

        transaction.on_commit(
            lambda: notify_maintenance_comment_created_task.delay(comment.id)
        )


class MaintenanceRequestCommentRetrieveUpdateDestroyView(RetrieveUpdateDestroyAPIView):
    serializer_class = MaintenanceRequestCommentSerializer
    permission_classes = [IsTenant | IsLandlord | IsAdmin | IsLettingAgent]
    lookup_field = "alias"
    lookup_url_kwarg = "comment_alias"

    def get_maintenance_request(self):
        user = self.request.user
        if isinstance(user, Tenant):
            return get_object_or_404(
                MaintenanceRequest,
                alias=self.kwargs["maintenance_request_alias"],
                tenant=user,
            )
        organisation = user.get_organisation()
        if not organisation:
            raise PermissionDenied("You are not part of an organisation.")
        return get_object_or_404(
            MaintenanceRequest,
            alias=self.kwargs["maintenance_request_alias"],
            organisation=organisation,
        )

    def get_queryset(self):
        return (
            MaintenanceRequestComment.objects.filter(
                maintenance_request=self.get_maintenance_request()
            )
            .select_related("staff_author", "tenant_author")
            .prefetch_related("documents", "replies")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["maintenance_request"] = self.get_maintenance_request()
        return context

    def perform_update(self, serializer):
        comment = self.get_object()
        if comment.author != self.request.user:
            raise PermissionDenied("You can only edit your own comment.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.author != self.request.user:
            raise PermissionDenied("You can only delete your own comment.")
        comment_id = instance.id
        instance.delete()
        mark_comment_notifications_deleted_task.delay(comment_id)


class TenantSharedComplianceListView(ListAPIView):
    serializer_class = ComplianceAndCertificationSerializers
    permission_classes = [IsTenant]

    def get_queryset(self):
        tenant = self.request.user
        return ComplianceAndCertification.objects.filter(
            shares__tenant=tenant
        ).order_by("-shares__created_at")


class TenantListAPiView(ListAPIView):
    serializer_class = TenantSerializer
    permission_classes = [IsLandlord | IsAdmin]
    pagination_class = None
    search_fields = [
        "property__property_name",
        "first_name",
        "last_name",
        "email",
        "phone",
    ]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")

        queryset = (
            Tenant.objects.filter(organisation=organisation)
            .select_related("property")
            .order_by("-created_at")
        )

        property_alias = self.request.query_params.get("property_alias")
        if property_alias:
            queryset = queryset.filter(property__alias=property_alias)

        compliance_alias = self.request.query_params.get("compliance_alias")
        if compliance_alias:
            queryset = queryset.exclude(
                compliance_shares__compliance__alias=compliance_alias,
                compliance_shares__compliance__organisation=organisation,
            )

        return queryset
