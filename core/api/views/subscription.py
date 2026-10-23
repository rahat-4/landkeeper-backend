import logging
from stripe import InvalidRequestError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.utils import timezone
import stripe
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings
from django.db import transaction
from rest_framework.generics import (
    ListAPIView,
    RetrieveUpdateAPIView,
    RetrieveUpdateDestroyAPIView,
    ListCreateAPIView,
)
from rest_framework.views import APIView
from rest_framework import status, serializers
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from api.serializers.subscription import (
    SubscriptionPlanSerializer,
    PaymentCardSerializer,
    BillingHistorySerializer,
    OrganisationSubscriptionStatusSerializer,
)
from apps.organisation.enums import OrganisationSubscriptionStatus
from apps.organisation.stripe_service import (
    handle_payment_success,
    handle_payment_failed,
    handle_invoice_payment_succeeded,
    handle_invoice_payment_failed,
    handle_subscription_deleted,
    handle_subscription_updated,
    create_subscription_with_client_secret,
    change_subscription_plan,
    PlanDowngradeBlockedError,
    sync_payment_method_to_organisation,
    schedule_plan_downgrade,
    get_pending_downgrade_info,
    cancel_pending_downgrade,
)
from apps.organisation.utils import get_request_organisation
from apps.subscription.models import SubscriptionPlan, PaymentCard, PaymentTransaction
from apps.organisation.models import OrganisationSubscription
from apps.property.models import Property
from apps.referral.utils import validate_coupon
from common.permission import IsLandlord

logger = logging.getLogger(__name__)


def _release_pending_schedule(current_subscription):
    stripe_sub = stripe.Subscription.retrieve(
        current_subscription.stripe_subscription_id
    )

    schedule_id = getattr(stripe_sub, "schedule", None)

    if not schedule_id:
        logger.info(
            "No pending subscription schedule found for subscription %s",
            current_subscription.stripe_subscription_id,
        )
        return

    stripe.SubscriptionSchedule.release(schedule_id)

    logger.info(
        "Released pending schedule %s for subscription %s before upgrade",
        schedule_id,
        current_subscription.stripe_subscription_id,
    )


class SelectSubscriptionView(APIView):

    def post(self, request):
        with transaction.atomic():
            plan_id = request.data.get("plan_id")
            payment_method_id = request.data.get("payment_method_id")

            if not plan_id:
                return Response(
                    {"detail": "plan_id is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                plan = SubscriptionPlan.objects.get(alias=plan_id, is_active=True)
            except SubscriptionPlan.DoesNotExist:
                return Response(
                    {"detail": "Subscription plan not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            organisation = request.user.get_organisation()

            current_subscription = (
                OrganisationSubscription.objects.filter(organisation=organisation)
                .select_related("plan")
                .first()
            )

            coupon = None
            coupon_code = request.data.get("coupon_code")

            if coupon_code:
                coupon, error_response = validate_coupon(coupon_code, request.user)
                if error_response:
                    return error_response

            if current_subscription:

                if current_subscription.status in (
                    OrganisationSubscriptionStatus.ACTIVE,
                    OrganisationSubscriptionStatus.TRIALING,
                ):
                    now = timezone.now()

                    if (
                        current_subscription.status
                        == OrganisationSubscriptionStatus.TRIALING
                    ):
                        period_over = (
                            current_subscription.trial_end_date is not None
                            and now >= current_subscription.trial_end_date
                        )
                    else:
                        period_over = (
                            current_subscription.next_billing_date is not None
                            and now >= current_subscription.next_billing_date
                        )

                    if not period_over:

                        if current_subscription.plan_id == plan.id:
                            return Response(
                                {"detail": "You are already subscribed to this plan."},
                                status=status.HTTP_400_BAD_REQUEST,
                            )

                        is_upgrade_request = (
                            plan.monthly_price > current_subscription.plan.monthly_price
                        )

                        if is_upgrade_request:
                            try:
                                _release_pending_schedule(current_subscription)

                                result = change_subscription_plan(organisation, plan)
                            except PlanDowngradeBlockedError as exc:
                                return Response(
                                    {
                                        "detail": (
                                            f"Cannot switch to '{plan.name}'. "
                                            f"You currently have {exc.current_property_count} "
                                            f"properties, but this plan only allows "
                                            f"{exc.max_properties}. Please remove "
                                            f"{exc.excess} properties before downgrading."
                                        ),
                                        "current_property_count": exc.current_property_count,
                                        "new_plan_max_properties": exc.max_properties,
                                        "properties_to_remove": exc.excess,
                                    },
                                    status=status.HTTP_400_BAD_REQUEST,
                                )
                            except InvalidRequestError as exc:
                                logger.warning(
                                    "Stripe rejected plan upgrade for org %s: %s",
                                    organisation.id,
                                    exc,
                                )
                                return Response(
                                    {
                                        "detail": (
                                            "We couldn't switch your plan because a plan "
                                            "change is already in progress on your "
                                            "subscription. Please try again in a moment, "
                                            "or contact support if this persists."
                                        )
                                    },
                                    status=status.HTTP_409_CONFLICT,
                                )

                            return Response(
                                {
                                    "detail": "Plan upgraded successfully.",
                                    "is_upgrade": True,
                                    "account_credit": str(result["account_credit"]),
                                    "requires_action": result["requires_action"],
                                    "client_secret": result["client_secret"],
                                },
                                status=status.HTTP_200_OK,
                            )
                        else:
                            try:
                                result = schedule_plan_downgrade(organisation, plan)
                            except PlanDowngradeBlockedError as exc:
                                return Response(
                                    {
                                        "detail": (
                                            f"Cannot switch to '{plan.name}'. "
                                            f"You currently have {exc.current_property_count} "
                                            f"properties, but this plan only allows "
                                            f"{exc.max_properties}. Please remove "
                                            f"{exc.excess} properties before downgrading."
                                        ),
                                        "current_property_count": exc.current_property_count,
                                        "new_plan_max_properties": exc.max_properties,
                                        "properties_to_remove": exc.excess,
                                    },
                                    status=status.HTTP_400_BAD_REQUEST,
                                )
                            except InvalidRequestError as exc:
                                logger.warning(
                                    "Stripe rejected scheduled downgrade for org %s: %s",
                                    organisation.id,
                                    exc,
                                )
                                return Response(
                                    {
                                        "detail": (
                                            "We couldn't schedule that plan change "
                                            "because a change is already in progress "
                                            "on your subscription. Please try again "
                                            "in a moment, or contact support if this "
                                            "persists."
                                        )
                                    },
                                    status=status.HTTP_409_CONFLICT,
                                )

                            return Response(result, status=status.HTTP_200_OK)

                if current_subscription.plan_id != plan.id:
                    current_property_count = (
                        organisation.organisation_properties.count()
                    )

                    if plan.max_properties < current_property_count:
                        excess = current_property_count - plan.max_properties
                        return Response(
                            {
                                "detail": (
                                    f"Cannot switch to '{plan.name}'. "
                                    f"You currently have {current_property_count} "
                                    f"properties, but this plan only allows "
                                    f"{plan.max_properties}. Please remove "
                                    f"{excess} properties before downgrading."
                                ),
                                "current_property_count": current_property_count,
                                "new_plan_max_properties": plan.max_properties,
                                "properties_to_remove": excess,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                result = create_subscription_with_client_secret(
                    organisation=organisation,
                    user=request.user,
                    plan=plan,
                    payment_method_id=payment_method_id,
                    affonso_coupon=coupon,
                )
                return Response(
                    {
                        "subscription_id": result["subscription_id"],
                        "client_secret": result["client_secret"],
                        "mode": result["mode"],
                    },
                    status=status.HTTP_200_OK,
                )

            # No subscription at all yet
            result = create_subscription_with_client_secret(
                organisation=organisation,
                user=request.user,
                plan=plan,
                payment_method_id=payment_method_id,
                affonso_coupon=coupon,
            )
            print("Result from create_subscription_with_client_secret:", coupon)
            organisation.coupon_code = coupon["code"] if coupon else None
            organisation.save(update_fields=["coupon_code"])

            return Response(
                {
                    "subscription_id": result["subscription_id"],
                    "client_secret": result["client_secret"],
                    "mode": result["mode"],
                },
                status=status.HTTP_200_OK,
            )


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):

    def post(self, request, *args, **kwargs):
        payload = request.body
        signature = request.META.get("HTTP_STRIPE_SIGNATURE")

        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                settings.STRIPE_WEBHOOK_SECRET,
            )
        except ValueError:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)

        event_type = event["type"]
        data = event["data"]["object"]

        # Keep old handlers for backward compat / direct PI events
        if event_type == "payment_intent.succeeded":
            handle_payment_success(data)

        elif event_type == "payment_intent.payment_failed":
            handle_payment_failed(data)

        elif event_type in ("invoice.payment_succeeded", "invoice.paid"):
            handle_invoice_payment_succeeded(data)

        elif event_type == "invoice.payment_failed":
            handle_invoice_payment_failed(data)

        elif event_type == "customer.subscription.deleted":
            handle_subscription_deleted(data)

        elif event_type == "customer.subscription.updated":
            handle_subscription_updated(data)

        return HttpResponse(status=200)


class SubscriptionPlanListView(ListAPIView):
    serializer_class = SubscriptionPlanSerializer

    def get_queryset(self):
        return (
            SubscriptionPlan.objects.filter(is_active=True)
            .prefetch_related("features")
            .order_by("monthly_price")
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()

        organisation = get_request_organisation(self.request)

        print("Organisation in context:", organisation)

        coupon_param = self.request.query_params.get("coupon_code")

        if coupon_param:
            coupon_code = coupon_param.strip().upper()
        else:
            coupon_code = organisation.coupon_code if organisation else None

        context["coupon"] = None

        if coupon_code:
            coupon, error_response = validate_coupon(
                coupon_code,
                self.request.user,
            )

            if error_response:
                raise serializers.ValidationError(
                    {"coupon_code": "Invalid or ineligible coupon."}
                )

            context["coupon"] = coupon

        return context


class LandlordPaymentCardUpdateDeleteAPIView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsLandlord]
    serializer_class = PaymentCardSerializer
    http_method_names = ["get", "patch", "delete"]
    lookup_field = "alias"
    lookup_url_kwarg = "alias"

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        return PaymentCard.objects.filter(organisation=organisation)

    def update(self, request, *args, **kwargs):
        organisation = self.request.user.get_organisation()
        instance = self.get_object()

        make_default = request.data.get("is_default", True)

        if make_default:
            return self._set_default(organisation, instance)
        else:
            return self._unset_default(organisation, instance)

    def _set_default(self, organisation, instance):
        if instance.is_default:
            return Response(
                {"detail": "This card is already the default."},
                status=status.HTTP_200_OK,
            )

        try:
            stripe.Customer.modify(
                organisation.stripe_customer_id,
                invoice_settings={
                    "default_payment_method": instance.stripe_payment_method_id
                },
            )
        except stripe.error.StripeError as exc:
            return Response(
                {"detail": f"Payment provider error: {exc.user_message or str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        with transaction.atomic():
            PaymentCard.objects.filter(
                organisation=organisation, is_default=True
            ).exclude(pk=instance.pk).update(is_default=False)

            instance.is_default = True
            instance.save(update_fields=["is_default"])

        serializer = self.get_serializer(instance)
        return Response(
            {
                "detail": "Default payment method updated.",
                "card": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def _unset_default(self, organisation, instance):
        if not instance.is_default:
            return Response(
                {"detail": "This card is not currently the default."},
                status=status.HTTP_200_OK,
            )

        with transaction.atomic():
            instance.is_default = False
            instance.save(update_fields=["is_default"])

        try:
            stripe.Customer.modify(
                organisation.stripe_customer_id,
                invoice_settings={"default_payment_method": ""},
            )
        except stripe.error.StripeError:
            pass

        serializer = self.get_serializer(instance)
        return Response(
            {
                "detail": "Default payment method removed. No card is currently set as default.",
                "card": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    def perform_destroy(self, instance):
        organisation = self.request.user.get_organisation()
        was_default = instance.is_default

        stripe.PaymentMethod.detach(instance.stripe_payment_method_id)
        instance.delete()

        if was_default:
            new_default = (
                PaymentCard.objects.filter(organisation=organisation)
                .order_by("-created_at")
                .first()
            )

            if new_default:
                new_default.is_default = True
                new_default.save(update_fields=["is_default"])

                stripe.Customer.modify(
                    organisation.stripe_customer_id,
                    invoice_settings={
                        "default_payment_method": (new_default.stripe_payment_method_id)
                    },
                )


class LandlordBillingHistoryAPIView(ListAPIView):
    serializer_class = BillingHistorySerializer
    permission_classes = [IsLandlord]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()

        return (
            PaymentTransaction.objects.filter(
                organisation=organisation,
            )
            .exclude(amount=0)
            .select_related(
                "subscription",
                "subscription__plan",
            )
            .order_by("-created_at")
        )


class LandlordSubscriptionAPIView(RetrieveUpdateAPIView):
    serializer_class = OrganisationSubscriptionStatusSerializer
    permission_classes = [IsLandlord]

    def get_serializer_context(self):
        context = super().get_serializer_context()

        organisation = get_request_organisation(self.request)

        print("Organisation in context:", organisation)

        coupon_param = self.request.query_params.get("coupon_code")

        if coupon_param:
            coupon_code = coupon_param.strip().upper()
        else:
            coupon_code = organisation.coupon_code if organisation else None

        context["coupon"] = None

        if coupon_code:
            coupon, error_response = validate_coupon(
                coupon_code,
                self.request.user,
            )

            if error_response:
                raise serializers.ValidationError(
                    {"coupon_code": "Invalid or ineligible coupon."}
                )

            context["coupon"] = coupon

        return context

    def get_object(self):
        organisation = self.request.user.get_organisation()

        return get_object_or_404(
            OrganisationSubscription.objects.select_related("plan"),
            organisation=organisation,
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data

        pending_info = get_pending_downgrade_info(instance)
        if pending_info:
            pending_plan = pending_info["plan"]
            data["pending_plan"] = {
                "alias": str(pending_plan.alias),
                "name": pending_plan.name,
                "plan_type": pending_plan.plan_type,
                "monthly_price": str(pending_plan.monthly_price),
                "max_properties": pending_plan.max_properties,
                "effective_date": pending_info["effective_date"],
            }
        else:
            data["pending_plan"] = None

        return Response(data)

    def perform_update(self, serializer):
        subscription = self.get_object()

        auto_renew = serializer.validated_data.get(
            "auto_renew",
            subscription.auto_renew,
        )

        if subscription.stripe_subscription_id:
            try:
                stripe.Subscription.modify(
                    subscription.stripe_subscription_id,
                    cancel_at_period_end=not auto_renew,
                )
            except stripe.error.InvalidRequestError:
                pass

        serializer.save(auto_renew=auto_renew)


class SubscriptionPermissionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        organisation = get_request_organisation(request)

        current_property_count = Property.objects.filter(
            organisation=organisation
        ).count()

        subscription = (
            OrganisationSubscription.objects.filter(organisation=organisation)
            .select_related("plan")
            .first()
        )

        max_properties = subscription.plan.max_properties if subscription else None

        # Superadmin no plan limit
        if request.user.is_superuser:
            return Response(
                {
                    "can_create_property": True,
                    "property_count": current_property_count,
                    "max_properties": max_properties,
                },
                status=status.HTTP_200_OK,
            )

        if not subscription:
            return Response(
                {"detail": "No subscription found for this organisation."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {
                "can_create_property": current_property_count < max_properties,
                "property_count": current_property_count,
                "max_properties": max_properties,
            },
            status=status.HTTP_200_OK,
        )


class LandlordPaymentCardCreateAPIView(ListCreateAPIView):
    permission_classes = [IsLandlord]
    serializer_class = PaymentCardSerializer

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        return PaymentCard.objects.filter(organisation=organisation).order_by(
            "-is_default", "-id"
        )

    def create(self, request, *args, **kwargs):
        payment_method_id = request.data.get("payment_method_id")
        set_default = request.data.get("is_default", True)

        if not payment_method_id:
            return Response(
                {"detail": "payment_method_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        organisation = request.user.get_organisation()

        if not organisation.stripe_customer_id:
            return Response(
                {"detail": "Organisation does not have a Stripe customer yet."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payment_card = sync_payment_method_to_organisation(
                organisation=organisation,
                payment_method_id=payment_method_id,
                set_default=set_default,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except stripe.error.StripeError as exc:
            return Response(
                {"detail": f"Payment provider error: {exc.user_message or str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        serializer = self.get_serializer(payment_card)
        return Response(
            {
                "detail": "Card added successfully.",
                "card": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class CancelPendingDowngradeAPIView(APIView):
    permission_classes = [IsLandlord]

    def post(self, request):
        organisation = request.user.get_organisation()
        if not organisation:
            return Response(
                {"error": "Organisation not found for the user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = cancel_pending_downgrade(organisation)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result, status=status.HTTP_200_OK)
