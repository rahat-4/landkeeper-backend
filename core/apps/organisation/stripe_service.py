import stripe
from django.conf import settings
from django.db import transaction
from apps.tenant.models import PaymentMethod, PaymentMethodStatusChoices, PaymentProviderChoices

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


def get_or_create_stripe_product(plan):
    if plan.stripe_product_id:
        return plan.stripe_product_id

    product = stripe.Product.create(
        name=plan.name,
        metadata={"plan_id": str(plan.id)},
    )
    plan.stripe_product_id = product.id
    plan.save(update_fields=["stripe_product_id"])
    return product.id


def create_checkout_session(organisation, user, plan, idempotency_key=None):
    customer_id = get_or_create_stripe_customer(organisation, user)

    return stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "gbp",
                    "unit_amount": int(plan.monthly_price * 100),
                    "recurring": {"interval": "month"},
                    "product_data": {
                        "name": plan.name,
                    },
                },
                "quantity": 1,
            }
        ],
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


def create_subscription_with_client_secret(
    organisation, user, plan, idempotency_key=None, payment_method=None
):
    customer_id = get_or_create_stripe_customer(organisation, user)
    product_id = get_or_create_stripe_product(plan)

    if payment_method:
        stripe.PaymentMethod.attach(payment_method, customer=customer_id)
        stripe.Customer.modify(
            customer_id,
            invoice_settings={"default_payment_method": payment_method},
        )

    subscription = stripe.Subscription.create(
        customer=customer_id,
        items=[
            {
                "price_data": {
                    "currency": "gbp",
                    "unit_amount": int(plan.monthly_price * 100),
                    "recurring": {"interval": "month"},
                    "product": product_id,
                },
            }
        ],
        default_payment_method=payment_method if payment_method else None,
        payment_behavior="default_incomplete" if not payment_method else "error_if_incomplete",
        payment_settings={"save_default_payment_method": "on_subscription"},
        expand=["latest_invoice.confirmation_secret"],
        metadata={"organisation_id": str(organisation.id), "plan_id": str(plan.id)},
        idempotency_key=idempotency_key,
    )

    return subscription

def sync_payment_method_to_organisation(organisation, payment_method_id, set_default=True):
    pm = stripe.PaymentMethod.retrieve(payment_method_id)
    card = getattr(pm, "card", None)

    with transaction.atomic():
        if set_default:
            PaymentMethod.objects.filter(
                organisation=organisation, provider=PaymentProviderChoices.STRIPE
            ).update(is_default=False)

        obj, _created = PaymentMethod.objects.update_or_create(
            organisation=organisation,
            provider=PaymentProviderChoices.STRIPE,
            provider_payment_method_id=pm.id,
            defaults={
                "method_type": "CARD",
                "provider_customer_id": getattr(pm, "customer", None),
                "status": PaymentMethodStatusChoices.ACTIVE,
                "is_default": set_default,
                "card_brand": getattr(card, "brand", None) if card else None,
                "card_last4": getattr(card, "last4", None) if card else None,
            },
        )
    return obj

def cancel_subscription(stripe_subscription_id, at_period_end=True):
    return stripe.Subscription.modify(
        stripe_subscription_id, cancel_at_period_end=at_period_end
    )


def get_checkout_session(session_id):
    return stripe.checkout.Session.retrieve(session_id, expand=["subscription"])