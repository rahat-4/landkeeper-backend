import stripe
from django.conf import settings
from django.db import transaction

stripe.api_key = settings.STRIPE_SECRET_KEY


def get_or_create_stripe_customer(organisation, user):
    with transaction.atomic():
        org = organisation.__class__.objects.select_for_update().get(pk=organisation.pk)
        if org.stripe_customer_id:
            return org.stripe_customer_id

        customer = stripe.Customer.create(
            name=org.name,
            email=user.email or None,
            metadata={"organisation_id": str(org.id)},
        )
        org.stripe_customer_id = customer.id
        org.save(update_fields=["stripe_customer_id"])
        return customer.id


def create_checkout_session(organisation, user, plan, idempotency_key=None):
    if not plan.stripe_price_id:
        raise ValueError(
            f"SubscriptionPlan '{plan.name}' has no stripe_price_id configured."
        )

    customer_id = get_or_create_stripe_customer(organisation, user)

    return stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
        success_url=settings.FRONTEND_PAYMENT_SUCCESS_URL
        + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=settings.FRONTEND_PAYMENT_CANCEL_URL,
        metadata={"organisation_id": str(organisation.id), "plan_id": str(plan.id)},
        subscription_data={
            "metadata": {
                "organisation_id": str(organisation.id),
                "plan_id": str(plan.id),
            }
        },
        idempotency_key=idempotency_key,
    )


def cancel_subscription(stripe_subscription_id, at_period_end=True):
    return stripe.Subscription.modify(
        stripe_subscription_id, cancel_at_period_end=at_period_end
    )


def get_checkout_session(session_id):
    return stripe.checkout.Session.retrieve(session_id, expand=["subscription"])
