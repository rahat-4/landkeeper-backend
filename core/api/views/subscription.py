import uuid
from django.db import transaction
from django.http import HttpResponse
from django.views import View
from django.utils import timezone
import stripe
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings
from rest_framework.generics import ListAPIView, DestroyAPIView, RetrieveUpdateAPIView
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response

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
)
from apps.subscription.models import SubscriptionPlan, PaymentCard, PaymentTransaction
from apps.organisation.models import OrganisationSubscription
from common.permission import IsLandlord


class SelectSubscriptionView(APIView):

    def post(self, request):
        plan_id = request.data.get("plan_id")

        if not plan_id:
            return Response(
                {"detail": "plan_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            plan = SubscriptionPlan.objects.get(
                alias=plan_id,
                is_active=True,
            )
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {"detail": "Subscription plan not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        organisation = request.user.get_organisation()

        current_subscription = (
            OrganisationSubscription.objects.filter(
                organisation=organisation,
            )
            .select_related("plan")
            .first()
        )

        if current_subscription:

            # RULE: ACTIVE subscription
            if current_subscription.status == OrganisationSubscriptionStatus.ACTIVE:

                now = timezone.now()
                billing_period_over = (
                    current_subscription.next_billing_date is not None
                    and now >= current_subscription.next_billing_date
                )

                # Case A: billing period NOT over yet → block switching entirely
                if not billing_period_over:

                    if current_subscription.plan_id == plan.id:
                        return Response(
                            {"detail": "You are already subscribed to this plan."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    return Response(
                        {
                            "detail": (
                                f"You already have an active subscription to "
                                f"'{current_subscription.plan.name}'. "
                                f"Please wait until it ends, or use the plan-change "
                                f"flow to switch plans."
                            ),
                            "current_plan": current_subscription.plan.name,
                            "next_billing_date": current_subscription.next_billing_date,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Case B: billing period IS over → treat as expired, allow switching
                # but still enforce the downgrade/property-count check below.
                # (fall through to the downgrade check)

            # RULE: Downgrade check (applies when switching to a plan
            # with fewer max_properties than currently used) — applies
            # whether the current subscription is ACTIVE-but-expired
            # or already PENDING/CANCELLED and the org still has
            # properties from a previous plan.
            if current_subscription.plan_id != plan.id:
                current_property_count = organisation.organisation_properties.count()

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

            # RULE: PENDING subscription → free to switch to ANY plan
            # (payment not completed yet, nothing "locked in")
            if current_subscription.status == OrganisationSubscriptionStatus.PENDING:

                if (
                    current_subscription.plan_id != plan.id
                    and current_subscription.stripe_subscription_id
                ):
                    try:
                        stripe.Subscription.cancel(
                            current_subscription.stripe_subscription_id
                        )
                    except stripe.error.InvalidRequestError:
                        pass

                result = create_subscription_with_client_secret(
                    organisation=organisation,
                    user=request.user,
                    plan=plan,
                )
                return Response(
                    {
                        "subscription_id": result["subscription_id"],
                        "client_secret": result["client_secret"],
                    },
                    status=status.HTTP_200_OK,
                )

            # RULE: ACTIVE but expired (billing period over) → allow new
            # subscription to be created for the selected plan.
            if current_subscription.status == OrganisationSubscriptionStatus.ACTIVE:
                result = create_subscription_with_client_secret(
                    organisation=organisation,
                    user=request.user,
                    plan=plan,
                )
                return Response(
                    {
                        "subscription_id": result["subscription_id"],
                        "client_secret": result["client_secret"],
                    },
                    status=status.HTTP_200_OK,
                )

        # No existing subscription at all → normal flow
        result = create_subscription_with_client_secret(
            organisation=organisation,
            user=request.user,
            plan=plan,
        )

        return Response(
            {
                "subscription_id": result["subscription_id"],
                "client_secret": result["client_secret"],
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

        # Primary handlers — these cover renewals correctly
        elif event_type == "invoice.payment_succeeded":
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
    # permission_classes = []

    def get_queryset(self):
        return (
            SubscriptionPlan.objects.filter(is_active=True)
            .prefetch_related("features")
            .order_by("monthly_price")
        )


class LandlordPaymentCardListAPIView(APIView):
    permission_classes = [IsLandlord]

    def get(self, request):
        organisation = request.user.get_organisation()

        cards = PaymentCard.objects.filter(organisation=organisation).order_by(
            "-is_default", "-id"
        )

        serializer = PaymentCardSerializer(cards, many=True)

        return Response(
            {
                "cards": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class LandlordPaymentCardDeleteAPIView(DestroyAPIView):
    permission_classes = [IsLandlord]
    lookup_field = "alias"
    lookup_url_kwarg = "alias"

    def get_queryset(self):
        organisation = self.request.user.get_organisation()

        return PaymentCard.objects.filter(organisation=organisation)

    def perform_destroy(self, instance):
        organisation = self.request.user.get_organisation()

        was_default = instance.is_default

        stripe.PaymentMethod.detach(instance.stripe_payment_method_id)

        instance.delete()

        if was_default:
            new_default = PaymentCard.objects.filter(organisation=organisation).first()

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
            .select_related(
                "subscription",
                "subscription__plan",
            )
            .order_by("-created_at")
        )


class LandlordSubscriptionAPIView(RetrieveUpdateAPIView):
    serializer_class = OrganisationSubscriptionStatusSerializer
    permission_classes = [IsLandlord]

    def get_object(self):
        organisation = self.request.user.get_organisation()

        return OrganisationSubscription.objects.select_related(
            "plan",
        ).get(
            organisation=organisation,
        )

    def perform_update(self, serializer):
        with transaction.atomic():
            subscription = self.get_object()

            auto_renew = serializer.validated_data.get(
                "auto_renew",
                subscription.auto_renew,
            )

            subscription.auto_renew = auto_renew
            subscription.save(update_fields=["auto_renew"])



class LandlordSubscriptionValidationAPIView(APIView):
    permission_classes = [IsLandlord]

    def post(self, request):
        organisation = request.user.get_organisation()
        plan_alias = request.data.get("plan")

        if not plan_alias:
            return Response(
                {
                    "allowed": False,
                    "error": "plan is required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            new_plan = SubscriptionPlan.objects.get(
                alias=plan_alias,
                is_active=True,
            )
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {
                    "allowed": False,
                    "error": "Invalid subscription plan",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_subscription = (
            OrganisationSubscription.objects.select_related("plan")
            .filter(
                organisation=organisation,
                status=OrganisationSubscriptionStatus.ACTIVE,
            )
            .first()
        )

        if not current_subscription:
            return Response(
                {
                    "allowed": True,
                    "message": ("No active subscription. " "Plan selection allowed."),
                    "plan": {
                        "alias": str(new_plan.alias),
                        "name": new_plan.name,
                        "price": str(new_plan.monthly_price),
                        "max_properties": new_plan.max_properties,
                    },
                },
                status=status.HTTP_200_OK,
            )

        current_plan = current_subscription.plan

        if current_plan.id == new_plan.id:
            return Response(
                {
                    "allowed": False,
                    "message": ("You are already subscribed " "to this plan."),
                },
                status=status.HTTP_200_OK,
            )

        now = timezone.now()

        if (
            current_subscription.next_billing_date
            and now < current_subscription.next_billing_date
        ):
            return Response(
                {
                    "allowed": False,
                    "message": (
                        "You cannot change your subscription "
                        "plan before the current billing "
                        "period ends."
                    ),
                    "current_plan": current_plan.name,
                    "current_period_end": (current_subscription.next_billing_date),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_property_count = organisation.organisation_properties.count()

        current_price = current_plan.monthly_price or 0
        new_price = new_plan.monthly_price or 0

        if new_price < current_price:
            if new_plan.max_properties < current_property_count:
                excess = current_property_count - new_plan.max_properties

                return Response(
                    {
                        "allowed": False,
                        "message": (f"Cannot switch to " f"'{new_plan.name}'."),
                        "errors": [
                            (
                                f"{current_property_count} properties "
                                f"active — new plan allows "
                                f"{new_plan.max_properties}. "
                                f"Please remove {excess} "
                                f"properties first."
                            )
                        ],
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(
            {
                "allowed": True,
                "message": "Plan change allowed.",
                "current_plan": {
                    "alias": str(current_plan.alias),
                    "name": current_plan.name,
                    "price": str(current_plan.monthly_price),
                    "max_properties": current_plan.max_properties,
                },
                "new_plan": {
                    "alias": str(new_plan.alias),
                    "name": new_plan.name,
                    "price": str(new_plan.monthly_price),
                    "max_properties": new_plan.max_properties,
                },
                "current_property_count": current_property_count,
            },
            status=status.HTTP_200_OK,
        )
