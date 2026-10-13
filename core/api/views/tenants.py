import logging
from django.conf import settings
import uuid
from io import BytesIO
import stripe
from django.db.models import Exists, OuterRef
from datetime import date, timedelta
from django.db import transaction
from django.db.models import Value, CharField
from django.db.models.functions import Cast, Concat, LPad
from django.http import FileResponse
from django.shortcuts import get_object_or_404
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
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import SearchFilter
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    ListAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers.tenants import (
    PaymentMethodSerializer,
    RentBalanceSummarySerializer,
    CardPaymentRequestSerializer,
    MaintenanceRequestSerializer,
    MaintenanceRequestCommentSerializer,
    LandlordCardPaymentSerializer,
    PaymentHistorySerializer,
)
from apps.organisation.stripe_connect import (
    sync_account_status_from_stripe,
)
from apps.organisation.utils import get_request_organisation
from apps.property.models import Tenant, ComplianceAndCertification, Property, ComplianceShare
from apps.tenant.enums import (
    RentPaymentStatusChoices,
    PaymentProviderChoices,
    PaymentMethodTypeChoices,
    PaymentMethodStatusChoices,
)
from apps.tenant.models import (
    PaymentMethod,
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
from common.permission import IsTenant, IsLandlord, IsAdmin, IsLettingAgent, IsSuperAdmin
from api.serializers.property import (
    ComplianceAndCertificationSerializers,
    TenantSerializer,
)

from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import HttpResponse
from apps.tenant.stripe_client import (
    handle_tenant_payment_succeeded,
    handle_tenant_payment_failed,
)

logger = logging.getLogger("apps.tenant.payments")


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
        instance.delete()


class CardPaymentView(APIView):
    permission_classes = [IsTenant]

    def post(self, request):
        serializer = CardPaymentRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data["amount"]
        payment_method_id = serializer.validated_data.get("payment_method_id")
        note = serializer.validated_data.get("note")

        tenant = request.user
        organisation = tenant.property.organisation

        due_date = self._calculate_current_due_date(tenant)

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

        if payment_method_id:
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
                    organisation=organisation,
                    due_date=due_date,
                    amount=amount,
                    note=note,
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
                    organisation=organisation,
                    due_date=due_date,
                    amount=amount,
                    note=note,
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
                organisation=organisation,
                due_date=due_date,
                amount=amount,
                note=note,
                provider_payment_id=intent.id,
                payment_method=payment_method_obj,
                status=RentPaymentStatusChoices.PROCESSING,
            )

            return Response(
                {"client_secret": intent.client_secret, "status": intent.status, "mode": "payment"},
                status=status.HTTP_201_CREATED,
            )

        else:
            try:
                intent = stripe.PaymentIntent.create(
                    amount=int(round(amount * 100)),
                    currency="gbp",
                    metadata={
                        "tenant_id": str(request.user.id),
                        "due_date": str(due_date),
                        "organisation_id": str(organisation.id),
                    },
                    transfer_data={"destination": organisation.stripe_account_id},
                    automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                )
            except stripe.error.StripeError as e:
                logger.exception(
                    "CardPaymentView: setup-mode PaymentIntent creation failed",
                    extra={
                        "tenant_id": request.user.id,
                        "organisation_id": organisation.id,
                        "stripe_error_type": type(e).__name__,
                    },
                )
                return Response(
                    {
                        "error": "Your landlord's payment account is not available. Please contact them."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            CardPayment.objects.create(
                alias=alias,
                tenant=request.user,
                organisation=organisation,
                due_date=due_date,
                amount=amount,
                note=note,
                provider_payment_id=intent.id,
                status=RentPaymentStatusChoices.PROCESSING,
            )

            return Response(
                {"client_secret": intent.client_secret, "status": intent.status, "mode": "setup"},
                status=status.HTTP_201_CREATED,
            )

    @staticmethod
    def _calculate_current_due_date(tenant):
        import calendar
        from datetime import date
        from django.utils import timezone

        today = timezone.localdate()
        rent_day = (tenant.tenancy_start_date or today).day
        year, month = today.year, today.month
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, min(rent_day, last_day))

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
            card_exp_month=getattr(card, "exp_month", None) if card else None,
            card_exp_year=getattr(card, "exp_year", None) if card else None,
        )


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

        card_payments = CardPayment.objects.filter(
            tenant=tenant,
            created_at__date__gte=start,
            created_at__date__lte=end,
        ).select_related("payment_method")

        rows = self._build_rows(card_payments)

        buffer = self.build_rent_statement_pdf(tenant, rows, period_label=label)
        filename = f"rent_statement_{period}_{start}_{end}.pdf"
        return FileResponse(buffer, as_attachment=True, filename=filename)

    @staticmethod
    def _payment_type_label(payment_method, fallback):
        if payment_method is None:
            return fallback
        if payment_method.provider == PaymentProviderChoices.STRIPE:
            return "Card"
        return payment_method.get_provider_display()

    @classmethod
    def _build_rows(cls, card_payments):
        """Build a date-sorted list of row dicts from CardPayment records, newest first."""
        rows = []

        for c in card_payments:
            rows.append(
                {
                    "date": c.created_at.date(),
                    "type": cls._payment_type_label(c.payment_method, "Card"),
                    "amount": c.amount,
                    "status": c.get_status_display(),
                }
            )

        rows.sort(key=lambda r: r["date"], reverse=True)
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
        total_cleared = 0
        for r in rows:
            data.append(
                [
                    r["date"].strftime("%d %b %Y"),
                    r["type"],
                    f"£{r['amount']:,.2f}",
                    r["status"],
                ]
            )
            if r["status"] == "Cleared":
                total_cleared += r["amount"]

        data.append(["", "", f"Total Paid: £{total_cleared:,.2f}", ""])

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

class PaymentHistoryView(ListAPIView):
    permission_classes = [IsTenant]
    serializer_class = PaymentHistorySerializer

    def get_queryset(self):
        tenant = self.request.user

        return (
            CardPayment.objects
            .filter(tenant=tenant)
            .select_related("payment_method")
            .order_by("-created_at")
        )


@method_decorator(csrf_exempt, name="dispatch")
class TenantStripeConnectWebhookView(View):

    def post(self, request, *args, **kwargs):
        logger.info("TenantStripeConnectWebhookView: request received")

        payload = request.body
        signature = request.META.get("HTTP_STRIPE_SIGNATURE")

        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                settings.STRIPE_CONNECT_WEBHOOK_SECRET,
            )
        except ValueError:
            logger.warning("TenantStripeConnectWebhookView: invalid payload")
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
            logger.warning("TenantStripeConnectWebhookView: signature verification failed")
            return HttpResponse(status=400)

        event_type = event["type"]
        data = event["data"]["object"]

        logger.info(f"TenantStripeConnectWebhookView: event_type={event_type}")

        if event_type == "payment_intent.succeeded":
            handle_tenant_payment_succeeded(data)
            logger.info(f"TenantStripeConnectWebhookView: handled succeeded for {getattr(data, 'id', None)}")

        elif event_type == "payment_intent.payment_failed":
            handle_tenant_payment_failed(data)

        return HttpResponse(status=200)


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
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]
    pagination_class = None
    search_fields = [
        "property__property_name",
        "first_name",
        "last_name",
        "email",
        "phone",
    ]

    def get_queryset(self):
        organisation = get_request_organisation(self.request)

        return (
            Tenant.objects.filter(organisation=organisation)
            .exclude(compliance_shares__isnull=False)
            .select_related("property")
            .order_by("-created_at")
        )


class TenantPaymentsListAPIView(ListAPIView):
    permission_classes = [IsLandlord | IsSuperAdmin]
    serializer_class = LandlordCardPaymentSerializer
    pagination_class = PageNumberPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["status"]
    search_fields = [
        "tenant__first_name",
        "tenant__last_name",
        "tenant__email",
        "tenant__property__property_name",
        "tenant__property__address",
    ]

    def get_queryset(self):
        organisation = get_request_organisation(self.request)
        return (
            CardPayment.objects.filter(organisation=organisation)
            .select_related("tenant", "tenant__property", "payment_method")
            .order_by("-created_at")
        )