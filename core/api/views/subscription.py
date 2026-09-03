import uuid

import stripe
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from datetime import timezone as dt_timezone

from rest_framework.exceptions import NotFound
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.generics import ListAPIView, CreateAPIView, RetrieveAPIView
from rest_framework import status
from rest_framework.response import Response

from apps.organisation.models import (
    Organisation,
    OrganisationSubscription,
    ProcessedWebhookEvent,
)
from apps.organisation.stripe_service import create_checkout_session
from apps.subscription.models import SubscriptionPlan

from common.permission import IsLandlord

from api.serializers.subscription import (
    SubscriptionPlanSerializer,
    SelectSubscriptionSerializer,
    OrganisationSubscriptionStatusSerializer,
)


class SubscriptionPlanListView(ListAPIView):
    serializer_class = SubscriptionPlanSerializer
    permission_classes = []

    def get_queryset(self):
        return (
            SubscriptionPlan.objects.filter(is_active=True)
            .prefetch_related("features")
            .order_by("monthly_price")
        )


class SelectSubscriptionView(CreateAPIView):
    serializer_class = SelectSubscriptionSerializer
    permission_classes = [IsLandlord]

    LOCKED_STATUSES = {
        OrganisationSubscription.Status.ACTIVE,
        OrganisationSubscription.Status.TRIALING,
        OrganisationSubscription.Status.PAST_DUE,
    }

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plan = serializer.validated_data["plan"]
        organisation = request.user.get_organisation()

        if not organisation:
            return Response(
                {"detail": "Organisation not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        existing = getattr(organisation, "subscription", None)
        if existing and existing.status in self.LOCKED_STATUSES:
            return Response(
                {
                    "detail": (
                        "This organisation already has a subscription. "
                        "Use the plan-change endpoint or billing portal to switch plans."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        idempotency_key = str(uuid.uuid4())

        try:
            session = create_checkout_session(
                organisation, request.user, plan, idempotency_key
            )
        except stripe.error.StripeError as exc:
            return Response(
                {"detail": f"Payment provider error: {exc.user_message or str(exc)}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            subscription, _created = OrganisationSubscription.objects.update_or_create(
                organisation=organisation,
                defaults={
                    "plan": plan,
                    "status": OrganisationSubscription.Status.PENDING,
                    "stripe_checkout_session_id": session.id,
                },
            )

        return Response(
            {
                "message": "Redirect the landlord to checkout_url to complete payment.",
                "checkout_url": session.url,
                "subscription": {
                    "plan": plan.name,
                    "plan_type": plan.plan_type,
                    "monthly_price": plan.monthly_price,
                    "status": subscription.status,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class SubscriptionStatusView(RetrieveAPIView):
    serializer_class = OrganisationSubscriptionStatusSerializer
    permission_classes = [IsLandlord]

    def get_object(self):
        organisation = self.request.user.get_organisation()
        if not organisation or not hasattr(organisation, "subscription"):
            raise NotFound("No subscription found for this organisation.")
        return organisation.subscription


def _get_nested(obj, *keys, default=None):
    """
    Safely get nested values from StripeObject/dict.
    """
    current = obj

    for key in keys:
        if current is None:
            return default

        try:
            current = current.get(key, default)
        except AttributeError:
            try:
                current = current[key]
            except (KeyError, TypeError):
                return default

        if current is None:
            return default

    return current


def _stripe_timestamp_to_datetime(timestamp):
    """
    Convert Stripe Unix timestamp to timezone-aware datetime.
    """
    if not timestamp:
        return None

    return timezone.datetime.fromtimestamp(
        timestamp,
        tz=dt_timezone.utc,
    )


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):

    permission_classes = []
    authentication_classes = []

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "webhook"

    def post(self, request, *args, **kwargs):

        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                settings.STRIPE_WEBHOOK_SECRET,
            )

        except ValueError:
            return Response(
                {"detail": "Invalid payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except stripe.error.SignatureVerificationError:
            return Response(
                {"detail": "Invalid signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        event_id = event["id"]

        _, created = ProcessedWebhookEvent.objects.get_or_create(
            stripe_event_id=event_id,
            defaults={
                "event_type": event["type"],
            },
        )

        if not created:
            return Response(status=status.HTTP_200_OK)

        handlers = {
            "checkout.session.completed": self._checkout_completed,
            "checkout.session.expired": self._checkout_expired,
            "customer.subscription.created": self._subscription_updated,
            "customer.subscription.updated": self._subscription_updated,
            "customer.subscription.deleted": self._subscription_cancelled,
            "invoice.payment_failed": self._payment_failed,
        }

        handler = handlers.get(event["type"])

        if handler:

            try:
                handler(event["data"]["object"])

            except stripe.error.StripeError:

                ProcessedWebhookEvent.objects.filter(stripe_event_id=event_id).delete()

                return Response(status=status.HTTP_502_BAD_GATEWAY)

            except Exception:

                # Delete event so Stripe can retry it
                ProcessedWebhookEvent.objects.filter(stripe_event_id=event_id).delete()

                raise

        return Response(status=status.HTTP_200_OK)

    def _checkout_completed(self, session):

        organisation_id = _get_nested(
            session,
            "metadata",
            "organisation_id",
        )

        plan_id = _get_nested(
            session,
            "metadata",
            "plan_id",
        )

        stripe_subscription_id = _get_nested(
            session,
            "subscription",
        )

        if not (organisation_id and plan_id and stripe_subscription_id):
            return

        try:

            organisation = Organisation.objects.get(id=organisation_id)

            plan = SubscriptionPlan.objects.get(id=plan_id)

        except (
            Organisation.DoesNotExist,
            SubscriptionPlan.DoesNotExist,
        ):
            return

        stripe_sub = stripe.Subscription.retrieve(stripe_subscription_id)

        period_start = _get_nested(
            stripe_sub,
            "current_period_start",
        )

        period_end = _get_nested(
            stripe_sub,
            "current_period_end",
        )

        current_period_start = _stripe_timestamp_to_datetime(period_start)

        current_period_end = _stripe_timestamp_to_datetime(period_end)

        existing = OrganisationSubscription.objects.filter(
            organisation=organisation
        ).first()

        started_at = (
            existing.started_at if existing and existing.started_at else timezone.now()
        )

        defaults = {
            "plan": plan,
            "status": (OrganisationSubscription.Status.ACTIVE),
            "stripe_subscription_id": (stripe_subscription_id),
            "stripe_checkout_session_id": (_get_nested(session, "id")),
            "started_at": started_at,
            "cancelled_at": None,
        }

        if current_period_start:
            defaults["current_period_start"] = current_period_start

        if current_period_end:
            defaults["current_period_end"] = current_period_end

        OrganisationSubscription.objects.update_or_create(
            organisation=organisation,
            defaults=defaults,
        )

    def _checkout_expired(self, session):

        organisation_id = _get_nested(
            session,
            "metadata",
            "organisation_id",
        )

        if not organisation_id:
            return

        OrganisationSubscription.objects.filter(
            organisation_id=organisation_id,
            status=(OrganisationSubscription.Status.PENDING),
            stripe_checkout_session_id=(_get_nested(session, "id")),
        ).update(status=(OrganisationSubscription.Status.EXPIRED))

    def _subscription_updated(self, sub_obj):

        stripe_subscription_id = _get_nested(
            sub_obj,
            "id",
        )

        if not stripe_subscription_id:
            return

        try:

            org_sub = OrganisationSubscription.objects.get(
                stripe_subscription_id=(stripe_subscription_id)
            )

        except OrganisationSubscription.DoesNotExist:
            return

        status_map = {
            "trialing": OrganisationSubscription.Status.TRIALING,
            "active": OrganisationSubscription.Status.ACTIVE,
            "past_due": OrganisationSubscription.Status.PAST_DUE,
            "canceled": OrganisationSubscription.Status.CANCELLED,
            "unpaid": OrganisationSubscription.Status.PAST_DUE,
            "incomplete_expired": OrganisationSubscription.Status.EXPIRED,
        }

        stripe_status = _get_nested(
            sub_obj,
            "status",
        )

        if stripe_status:

            org_sub.status = status_map.get(
                stripe_status,
                org_sub.status,
            )

        period_start = _get_nested(
            sub_obj,
            "current_period_start",
        )

        period_end = _get_nested(
            sub_obj,
            "current_period_end",
        )

        if period_start:

            org_sub.current_period_start = _stripe_timestamp_to_datetime(period_start)

        if period_end:

            org_sub.current_period_end = _stripe_timestamp_to_datetime(period_end)

        org_sub.save()

    def _subscription_cancelled(self, sub_obj):

        stripe_subscription_id = _get_nested(
            sub_obj,
            "id",
        )

        if not stripe_subscription_id:
            return

        OrganisationSubscription.objects.filter(
            stripe_subscription_id=(stripe_subscription_id)
        ).update(
            status=(OrganisationSubscription.Status.CANCELLED),
            cancelled_at=timezone.now(),
        )

    def _payment_failed(self, invoice_obj):

        subscription_id = _get_nested(
            invoice_obj,
            "subscription",
        )

        if not subscription_id:
            return

        OrganisationSubscription.objects.filter(
            stripe_subscription_id=subscription_id
        ).update(status=(OrganisationSubscription.Status.PAST_DUE))
