from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views import View
import stripe
from django.conf import settings
from rest_framework.generics import (
    ListAPIView,
    DestroyAPIView,
    RetrieveUpdateAPIView
)
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response

from api.serializers.subscription import (
    SubscriptionPlanSerializer,
    PaymentCardSerializer,
    BillingHistorySerializer,
    OrganisationSubscriptionStatusSerializer
)
from apps.organisation.stripe_service import (
    handle_payment_success,
    handle_payment_failed,
    create_subscription_with_client_secret,
)
from apps.subscription.models import (
    SubscriptionPlan,
    PaymentCard,
    PaymentTransaction
)
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



class StripeWebhookView(View):

    def post(self, request, *args, **kwargs):

        payload = request.body
        signature = request.META.get(
            "HTTP_STRIPE_SIGNATURE"
        )

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

        if event_type == "payment_intent.succeeded":
            handle_payment_success(data)

        elif event_type == "payment_intent.payment_failed":
            handle_payment_failed(data)

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


class SubscriptionStatusView(APIView):

    def get(self, request):
        organisation = request.user.get_organisation()

        try:
            subscription = (
                OrganisationSubscription.objects
                .select_related("plan")
                .get(organisation=organisation)
            )

        except OrganisationSubscription.DoesNotExist:
            return Response(
                {
                    "has_subscription": False,
                    "subscription": None,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "has_subscription": True,
                "subscription": {
                    "plan": subscription.plan.name,
                    "plan_alias": str(subscription.plan.alias),
                    "status": subscription.status,
                    "monthly_price": subscription.plan.monthly_price,
                    "start_date": subscription.start_date,
                    "end_date": subscription.end_date,
                    "next_billing_date": subscription.next_billing_date,
                    "auto_renew": subscription.auto_renew,
                    "cancelled_at": subscription.cancelled_at,
                },
            },
            status=status.HTTP_200_OK,
        )


class LandlordPaymentCardListAPIView(APIView):
    permission_classes = [IsLandlord]

    def get(self, request):
        organisation = request.user.get_organisation()

        cards = PaymentCard.objects.filter(
            organisation=organisation
        ).order_by("-is_default", "-id")

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

        return PaymentCard.objects.filter(
            organisation=organisation
        )

    def perform_destroy(self, instance):
        organisation = self.request.user.get_organisation()

        was_default = instance.is_default

        stripe.PaymentMethod.detach(
            instance.stripe_payment_method_id
        )

        instance.delete()

        if was_default:
            new_default = (
                PaymentCard.objects
                .filter(organisation=organisation)
                .first()
            )

            if new_default:
                new_default.is_default = True
                new_default.save(update_fields=["is_default"])

                stripe.Customer.modify(
                    organisation.stripe_customer_id,
                    invoice_settings={
                        "default_payment_method": (
                            new_default.stripe_payment_method_id
                        )
                    },
                )

class LandlordBillingHistoryAPIView(ListAPIView):
    serializer_class = BillingHistorySerializer
    permission_classes = [IsLandlord]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()

        return (
            PaymentTransaction.objects
            .filter(
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
            subscription.save(
                update_fields=["auto_renew"]
            )

class LandlordSubscriptionValidationAPIView(APIView):
    permission_classes = [IsLandlord]

    def post(self, request):
        organisation = request.user.get_organisation()
        plan_alias = request.data.get("plan")

        if not plan_alias:
            return Response(
                {"error": "plan is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get new plan
        try:
            new_plan = SubscriptionPlan.objects.get(
                alias=plan_alias,
                is_active=True,
            )
        except SubscriptionPlan.DoesNotExist:
            return Response(
                {"error": "Invalid subscription plan"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get current subscription
        try:
            current_subscription = (
                OrganisationSubscription.objects
                .select_related("plan")
                .get(organisation=organisation)
            )
        except OrganisationSubscription.DoesNotExist:
            return Response(
                {
                    "allowed": True,
                    "message": "No active subscription. Plan selection allowed.",
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

        # Same plan
        if current_plan.id == new_plan.id:
            return Response(
                {
                    "allowed": False,
                    "message": "You are already subscribed to this plan.",
                },
                status=status.HTTP_200_OK,
            )

        # Prevent plan change before current billing period ends
        now = timezone.now()

        if (
            current_subscription.next_billing_date
            and now < current_subscription.next_billing_date
        ):
            return Response(
                {
                    "allowed": False,
                    "message": (
                        "You cannot change your subscription plan "
                        "before the current billing period ends."
                    ),
                    "current_plan": current_plan.name,
                    "current_period_end": (
                        current_subscription.next_billing_date
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Downgrade validation
        current_property_count = organisation.properties.count()

        downgrade_errors = []

        if (
            new_plan.monthly_price
            < current_plan.monthly_price
        ):
            if new_plan.max_properties < current_property_count:
                excess = (
                    current_property_count
                    - new_plan.max_properties
                )

                downgrade_errors.append(
                    f"{current_property_count} properties active — "
                    f"new plan allows {new_plan.max_properties}. "
                    f"Please remove {excess} properties first."
                )

        if downgrade_errors:
            return Response(
                {
                    "allowed": False,
                    "message": f"Cannot switch to '{new_plan.name}'.",
                    "errors": downgrade_errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "allowed": True,
                "message": "Plan change allowed.",
                "plan": {
                    "alias": str(new_plan.alias),
                    "name": new_plan.name,
                    "price": str(new_plan.monthly_price),
                    "max_properties": new_plan.max_properties,
                },
            },
            status=status.HTTP_200_OK,
        )