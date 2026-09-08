import stripe
from django.conf import settings
from django.db import transaction
from decimal import Decimal

from apps.organisation.enums import OrganisationSubscriptionStatus
from apps.organisation.models import Organisation, OrganisationSubscription
from apps.subscription.enums import PaymentTransactionStatus
from apps.subscription.models import PaymentCard, PaymentTransaction


stripe.api_key = settings.STRIPE_SECRET_KEY

# STRIPE CUSTOMER
def get_or_create_stripe_customer(organisation, user):
    with transaction.atomic():
        organisation = (
            Organisation.objects
            .select_for_update()
            .get(pk=organisation.pk)
        )

        if organisation.stripe_customer_id:
            return organisation.stripe_customer_id

        customer = stripe.Customer.create(
            name=organisation.name,
            email=user.email or None,
            metadata={
                "organisation_id": str(organisation.id),
            },
        )
        organisation.stripe_customer_id = customer.id
        organisation.save(
            update_fields=["stripe_customer_id"]
        )
        return customer.id


# STRIPE PRODUCT
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

# STRIPE PRICE
def get_or_create_stripe_price(plan):
    if plan.stripe_price_id:
        return plan.stripe_price_id

    product_id = get_or_create_stripe_product(plan)

    if plan.monthly_price is None:
        raise ValueError(
            f"Subscription plan '{plan.name}' has no monthly price."
        )

    amount = int(
        Decimal(plan.monthly_price) * Decimal("100")
    )

    price = stripe.Price.create(
        product=product_id,
        currency="gbp",
        unit_amount=amount,
        recurring={
            "interval": "month",
        },
        metadata={
            "plan_id": str(plan.id),
        },
    )

    plan.stripe_price_id = price.id

    plan.save(
        update_fields=["stripe_price_id"]
    )

    return price.id


# PAYMENT METHOD
def attach_payment_method(
    customer_id,
    payment_method_id,
    set_default=True,
):

    payment_method = stripe.PaymentMethod.retrieve(
        payment_method_id
    )

    # Don't attach again if already attached
    if payment_method.customer != customer_id:
        payment_method = stripe.PaymentMethod.attach(
            payment_method_id,
            customer=customer_id,
        )

    if set_default:
        stripe.Customer.modify(
            customer_id,
            invoice_settings={
                "default_payment_method": payment_method.id,
            },
        )

    return payment_method


def sync_payment_method_to_organisation(
    organisation,
    payment_method_id,
    set_default=True,
):

    customer_id = organisation.stripe_customer_id

    if not customer_id:
        raise ValueError(
            "Organisation does not have a Stripe customer."
        )

    payment_method = attach_payment_method(
        customer_id=customer_id,
        payment_method_id=payment_method_id,
        set_default=set_default,
    )

    card = payment_method.card

    if not card:
        raise ValueError(
            "The Stripe PaymentMethod does not contain card information."
        )

    with transaction.atomic():

        if set_default:
            PaymentCard.objects.filter(
                organisation=organisation,
                is_default=True,
            ).update(
                is_default=False
            )

        payment_card, _ = PaymentCard.objects.update_or_create(
            stripe_payment_method_id=payment_method.id,
            defaults={
                "organisation": organisation,
                "last_four": card.last4,
                "card_brand": card.brand,
                "expiry_month": card.exp_month,
                "expiry_year": card.exp_year,
                "is_default": set_default,
            },
        )

    return payment_card



# CREATE SUBSCRIPTION DIRECTLY
def create_subscription_with_client_secret(
    organisation,
    user,
    plan,
    payment_method_id=None,
    idempotency_key=None,
):
    customer_id = get_or_create_stripe_customer(
        organisation=organisation,
        user=user,
    )

    price_id = get_or_create_stripe_price(plan)

    if payment_method_id:
        attach_payment_method(
            customer_id=customer_id,
            payment_method_id=payment_method_id,
            set_default=True,
        )

    subscription_params = {
        "customer": customer_id,
        "items": [
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        "payment_behavior": "default_incomplete",
        "payment_settings": {
            "save_default_payment_method": "on_subscription",
        },
        "metadata": {
            "organisation_id": str(organisation.id),
            "plan_id": str(plan.id),
        },
        "expand": [
            "latest_invoice.confirmation_secret",
        ],
    }

    if payment_method_id:
        subscription_params["default_payment_method"] = payment_method_id

    if idempotency_key:
        stripe_subscription = stripe.Subscription.create(
            **subscription_params,
            idempotency_key=idempotency_key,
        )
    else:
        stripe_subscription = stripe.Subscription.create(
            **subscription_params,
        )

    # CREATE / UPDATE LOCAL SUBSCRIPTION
    OrganisationSubscription.objects.update_or_create(
        organisation=organisation,
        defaults={
            "plan": plan,
            "status": OrganisationSubscriptionStatus.PENDING,
            "stripe_subscription_id": stripe_subscription.id,
            "auto_renew": True,
        },
    )

    return {
        "subscription_id": stripe_subscription.id,
        "client_secret": (
            stripe_subscription
            .latest_invoice
            .confirmation_secret
            .client_secret
        ),
    }


# PAYMENT INTENT
def create_payment_transaction(
    organisation,
    subscription,
    amount,
    currency="GBP",
):

    return PaymentTransaction.objects.create(
        organisation=organisation,
        subscription=subscription,
        amount=amount,
        currency=currency.upper(),
        status=PaymentTransactionStatus.PENDING,
    )

# PAYMENT SUCCESS
def handle_payment_success(payment_intent):

    customer_id = payment_intent.get("customer")
    payment_intent_id = payment_intent.get("id")

    if not customer_id or not payment_intent_id:
        return

    try:
        organisation = Organisation.objects.get(
            stripe_customer_id=customer_id
        )

        payment_transaction = PaymentTransaction.objects.get(
            organisation=organisation,
            stripe_payment_intent_id=payment_intent_id,
        )

    except (
        Organisation.DoesNotExist,
        PaymentTransaction.DoesNotExist,
    ):
        return

    payment_transaction.status = (
        PaymentTransactionStatus.SUCCEEDED
    )

    payment_transaction.save(
        update_fields=["status"]
    )

    subscription = payment_transaction.subscription

    subscription.status = (
        OrganisationSubscriptionStatus.ACTIVE
    )

    subscription.save(
        update_fields=["status"]
    )


# PAYMENT FAILED
def handle_payment_failed(payment_intent):

    customer_id = payment_intent.get("customer")
    payment_intent_id = payment_intent.get("id")

    if not customer_id or not payment_intent_id:
        return

    try:
        organisation = Organisation.objects.get(
            stripe_customer_id=customer_id
        )

        payment_transaction = PaymentTransaction.objects.get(
            organisation=organisation,
            stripe_payment_intent_id=payment_intent_id,
        )

    except (
        Organisation.DoesNotExist,
        PaymentTransaction.DoesNotExist,
    ):
        return

    payment_transaction.status = (
        PaymentTransactionStatus.FAILED
    )

    payment_transaction.save(
        update_fields=["status"]
    )


# UPDATE PAYMENT TRANSACTION
def update_payment_transaction_from_intent(
    payment_intent,
):

    customer_id = payment_intent.get("customer")
    payment_intent_id = payment_intent.get("id")

    if not customer_id or not payment_intent_id:
        return None

    try:
        organisation = Organisation.objects.get(
            stripe_customer_id=customer_id
        )
    except Organisation.DoesNotExist:
        return None

    try:
        payment_transaction = (
            PaymentTransaction.objects
            .select_related("subscription")
            .get(
                organisation=organisation,
                stripe_payment_intent_id=payment_intent_id,
            )
        )

    except PaymentTransaction.DoesNotExist:
        return None

    payment_transaction.amount = (
        Decimal(payment_intent["amount"]) / Decimal("100")
    )

    payment_transaction.currency = (
        payment_intent["currency"].upper()
    )

    payment_transaction.save(
        update_fields=[
            "amount",
            "currency",
        ]
    )

    return payment_transaction



# SUBSCRIPTION PLAN CHANGE
def change_subscription_plan(
    organisation,
    new_plan,
    proration_behavior="create_prorations",
):

    organisation_subscription = getattr(
        organisation,
        "subscription",
        None,
    )

    if not organisation_subscription:
        raise ValueError(
            "Organisation has no subscription."
        )

    if not organisation_subscription.stripe_subscription_id:
        raise ValueError(
            "Organisation has no Stripe subscription."
        )

    price_id = get_or_create_stripe_price(new_plan)

    stripe_subscription = stripe.Subscription.retrieve(
        organisation_subscription.stripe_subscription_id
    )

    items = stripe_subscription.get("items", {}).get(
        "data",
        []
    )

    if not items:
        raise ValueError(
            "Stripe subscription has no subscription items."
        )

    subscription_item_id = items[0]["id"]

    updated_subscription = stripe.Subscription.modify(
        organisation_subscription.stripe_subscription_id,

        items=[
            {
                "id": subscription_item_id,
                "price": price_id,
            }
        ],

        proration_behavior=proration_behavior,

        metadata={
            "organisation_id": str(organisation.id),
            "plan_id": str(new_plan.id),
        },
    )

    return updated_subscription



# CANCEL SUBSCRIPTION
def cancel_subscription(
    stripe_subscription_id,
    at_period_end=True,
):

    return stripe.Subscription.modify(
        stripe_subscription_id,
        cancel_at_period_end=at_period_end,
    )

# GET CHECKOUT SESSION
def get_checkout_session(session_id):

    return stripe.checkout.Session.retrieve(
        session_id,
        expand=[
            "subscription",
        ],
    )

# GET STRIPE SUBSCRIPTION
def get_stripe_subscription(
    stripe_subscription_id,
):

    return stripe.Subscription.retrieve(
        stripe_subscription_id
    )

# LIST PAYMENT METHODS
def list_stripe_payment_methods(
    organisation,
):

    customer_id = organisation.stripe_customer_id

    if not customer_id:
        return []

    payment_methods = stripe.PaymentMethod.list(
        customer=customer_id,
        type="card",
    )

    return payment_methods.data


# DELETE / DETACH PAYMENT METHOD
def detach_payment_method(
    organisation,
    payment_card,
):

    if (
        payment_card.organisation_id
        != organisation.id
    ):
        raise ValueError(
            "Payment card does not belong to this organisation."
        )

    payment_method_id = (
        payment_card.stripe_payment_method_id
    )

    stripe.PaymentMethod.detach(
        payment_method_id
    )

    payment_card.delete()



# SET DEFAULT PAYMENT METHOD
def set_default_payment_method(
    organisation,
    payment_card,
):
    if (
        payment_card.organisation_id
        != organisation.id
    ):
        raise ValueError(
            "Payment card does not belong to this organisation."
        )

    customer_id = organisation.stripe_customer_id

    if not customer_id:
        raise ValueError(
            "Organisation does not have a Stripe customer."
        )

    stripe.Customer.modify(
        customer_id,
        invoice_settings={
            "default_payment_method": (
                payment_card.stripe_payment_method_id
            ),
        },
    )

    with transaction.atomic():

        PaymentCard.objects.filter(
            organisation=organisation,
            is_default=True,
        ).update(
            is_default=False
        )

        payment_card.is_default = True

        payment_card.save(
            update_fields=["is_default"]
        )

    return payment_card