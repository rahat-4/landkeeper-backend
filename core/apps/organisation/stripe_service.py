import stripe
from django.conf import settings
from django.db import transaction
from decimal import Decimal
from datetime import timezone
from datetime import datetime
from django.utils import timezone as django_timezone
from apps.organisation.enums import OrganisationSubscriptionStatus
from apps.organisation.models import Organisation, OrganisationSubscription
from apps.subscription.enums import PaymentTransactionStatus
from apps.subscription.models import PaymentCard, PaymentTransaction, SubscriptionPlan

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
    # reuse existing pending subscription for the SAME plan
    existing = OrganisationSubscription.objects.filter(
        organisation=organisation,
        plan=plan,
        status=OrganisationSubscriptionStatus.PENDING,
    ).first()

    if existing and existing.stripe_subscription_id:
        try:
            stripe_subscription = stripe.Subscription.retrieve(
                existing.stripe_subscription_id,
                expand=["latest_invoice.confirmation_secret"],
            )

            # Only reuse if payment hasn't been completed yet
            if stripe_subscription.status == "incomplete":
                confirmation_secret = (
                    stripe_subscription.latest_invoice.confirmation_secret
                )
                if confirmation_secret:
                    return {
                        "subscription_id": stripe_subscription.id,
                        "client_secret": confirmation_secret.client_secret,
                    }

        except stripe.error.InvalidRequestError:
            # Stripe subscription no longer exists
            # fall through and create a fresh one below
            pass

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

    # LOCAL SUBSCRIPTION
    local_subscription, _ = (
        OrganisationSubscription.objects.update_or_create(
            organisation=organisation,
            defaults={
                "plan": plan,
                "status": OrganisationSubscriptionStatus.PENDING,
                "stripe_subscription_id": stripe_subscription.id,
                "auto_renew": True,
            },
        )
    )

    # GET PAYMENT INTENT ID
    invoice = stripe.Invoice.retrieve(
        stripe_subscription.latest_invoice.id
    )

    invoice_payments = stripe.InvoicePayment.list(
        invoice=invoice.id
    )

    payment_intent_id = None

    for invoice_payment in invoice_payments.data:
        payment = invoice_payment.payment

        if payment and payment.type == "payment_intent":
            payment_intent_id = payment.payment_intent
            break

    # LOCAL PAYMENT TRANSACTION
    if payment_intent_id:
        PaymentTransaction.objects.get_or_create(
            organisation=organisation,
            stripe_payment_intent_id=payment_intent_id,
            defaults={
                "subscription": local_subscription,
                "amount": plan.monthly_price,
                "currency": "GBP",
                "status": PaymentTransactionStatus.PENDING,
                "attempt_number": 1,
            },
        )

    # RESPONSE
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
    customer_id = payment_intent.customer
    payment_intent_id = payment_intent.id

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

    # PAYMENT TRANSACTION
    payment_transaction.status = (
        PaymentTransactionStatus.SUCCEEDED
    )

    update_fields = ["status"]

    if payment_intent.invoice:
        payment_transaction.stripe_invoice_id = payment_intent.invoice
        update_fields.append("stripe_invoice_id")

        try:
            invoice = stripe.Invoice.retrieve(payment_intent.invoice)
            payment_transaction.invoice_pdf_url = invoice.invoice_pdf
            update_fields.append("invoice_pdf_url")
        except stripe.error.StripeError:
            pass

    payment_transaction.save(
        update_fields=update_fields
    )

    # SAVE PAYMENT CARD
    payment_method_id = payment_intent.payment_method

    if payment_method_id:
        payment_method = stripe.PaymentMethod.retrieve(
            payment_method_id
        )

        card = payment_method.card

        if card:
            with transaction.atomic():

                # Remove old default card
                PaymentCard.objects.filter(
                    organisation=organisation,
                    is_default=True,
                ).exclude(
                    stripe_payment_method_id=payment_method.id
                ).update(
                    is_default=False
                )

                # Save current card as default
                PaymentCard.objects.update_or_create(
                    stripe_payment_method_id=payment_method.id,
                    defaults={
                        "organisation": organisation,
                        "last_four": card.last4,
                        "card_brand": card.brand,
                        "expiry_month": card.exp_month,
                        "expiry_year": card.exp_year,
                        "is_default": True,
                    },
                )

    # GET LOCAL SUBSCRIPTION
    subscription = payment_transaction.subscription

    # GET STRIPE SUBSCRIPTION
    stripe_subscription = stripe.Subscription.retrieve(
        subscription.stripe_subscription_id
    )

    # GET SUBSCRIPTION ITEM
    subscription_item = stripe_subscription.items.data[0]

    # UPDATE LOCAL SUBSCRIPTION
    subscription.status = OrganisationSubscriptionStatus.ACTIVE

    subscription.start_date = datetime.fromtimestamp(
        stripe_subscription.start_date,
        tz=timezone.utc,
    )

    period_end = datetime.fromtimestamp(
        subscription_item.current_period_end,
        tz=timezone.utc,
    )
    subscription.end_date = period_end
    subscription.next_billing_date = period_end

    subscription.auto_renew = not stripe_subscription.cancel_at_period_end

    subscription.save(
        update_fields=[
            "status",
            "start_date",
            "end_date",
            "next_billing_date",
            "auto_renew",
        ]
    )

# PAYMENT FAILED
def handle_payment_failed(payment_intent):
    customer_id = payment_intent.customer
    payment_intent_id = payment_intent.id

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

    payment_transaction.status = PaymentTransactionStatus.FAILED
    payment_transaction.save(update_fields=["status"])


# UPDATE PAYMENT TRANSACTION
def update_payment_transaction_from_intent(payment_intent):
    customer_id = payment_intent.customer
    payment_intent_id = payment_intent.id

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
        Decimal(payment_intent.amount) / Decimal("100")
    )

    payment_transaction.currency = (
        payment_intent.currency.upper()
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
    if payment_card.organisation_id != organisation.id:
        raise ValueError(
            "Payment card does not belong to this organisation."
        )

    customer_id = organisation.stripe_customer_id

    if not customer_id:
        raise ValueError(
            "Organisation does not have a Stripe customer."
        )

    payment_method_id = payment_card.stripe_payment_method_id
    was_default = payment_card.is_default

    # Detach card from Stripe
    stripe.PaymentMethod.detach(payment_method_id)

    # Delete local card
    payment_card.delete()

    # If deleted card was NOT default,
    # nothing else needs to be done
    if not was_default:
        return

    # Find another card
    new_default_card = (
        PaymentCard.objects
        .filter(
            organisation=organisation,
        )
        .order_by("-id")
        .first()
    )

    # No cards left
    if not new_default_card:
        stripe.Customer.modify(
            customer_id,
            invoice_settings={
                "default_payment_method": None,
            },
        )
        return

    # Make another card default in Stripe
    stripe.Customer.modify(
        customer_id,
        invoice_settings={
            "default_payment_method": (
                new_default_card.stripe_payment_method_id
            ),
        },
    )

    # Make it default in local DB
    new_default_card.is_default = True
    new_default_card.save(
        update_fields=["is_default"]
    )


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


# INVOICE PAYMENT SUCCEEDED (handles both first payment AND renewals)
def handle_invoice_payment_succeeded(invoice):
    customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")

    if not customer_id or not subscription_id:
        return

    try:
        organisation = Organisation.objects.get(
            stripe_customer_id=customer_id
        )
        local_subscription = OrganisationSubscription.objects.get(
            organisation=organisation,
            stripe_subscription_id=subscription_id,
        )
    except (
        Organisation.DoesNotExist,
        OrganisationSubscription.DoesNotExist,
    ):
        return

    # Get payment_intent id from the invoice
    invoice_payments = stripe.InvoicePayment.list(invoice=invoice["id"])
    payment_intent_id = None

    for invoice_payment in invoice_payments.data:
        payment = invoice_payment.payment
        if payment and payment.type == "payment_intent":
            payment_intent_id = payment.payment_intent
            break

    amount_paid = Decimal(invoice.get("amount_paid", 0)) / Decimal("100")

    with transaction.atomic():
        # get_or_create so first payment (already created in
        # create_subscription_with_client_secret) is not duplicated,
        # but every future renewal creates a fresh row
        payment_transaction, created = PaymentTransaction.objects.get_or_create(
            organisation=organisation,
            stripe_payment_intent_id=payment_intent_id,
            defaults={
                "subscription": local_subscription,
                "amount": amount_paid,
                "currency": invoice.get("currency", "gbp").upper(),
                "status": PaymentTransactionStatus.SUCCEEDED,
                "attempt_number": 1,
                "stripe_invoice_id": invoice.get("id"),
                "invoice_pdf_url": invoice.get("invoice_pdf"),
            },
        )

        if not created:
            payment_transaction.status = PaymentTransactionStatus.SUCCEEDED
            payment_transaction.amount = amount_paid
            payment_transaction.stripe_invoice_id = invoice.get("id")
            payment_transaction.invoice_pdf_url = invoice.get("invoice_pdf")
            payment_transaction.save(
                update_fields=[
                    "status",
                    "amount",
                    "stripe_invoice_id",
                    "invoice_pdf_url",
                ]
            )

    # Sync subscription status/dates from Stripe (covers renewals too)
    stripe_subscription = stripe.Subscription.retrieve(subscription_id)
    subscription_item = stripe_subscription.items.data[0]

    local_subscription.status = OrganisationSubscriptionStatus.ACTIVE
    local_subscription.start_date = local_subscription.start_date or datetime.fromtimestamp(
        stripe_subscription.start_date, tz=timezone.utc,
    )
    local_subscription.end_date = datetime.fromtimestamp(
        subscription_item.current_period_end,
        tz=timezone.utc,
    )
    local_subscription.next_billing_date = datetime.fromtimestamp(
        subscription_item.current_period_end, tz=timezone.utc,
    )
    local_subscription.auto_renew = not stripe_subscription.cancel_at_period_end
    local_subscription.save(
        update_fields=[
            "status",
            "start_date",
            "end_date",
            "next_billing_date",
            "auto_renew",
        ]
    )

# INVOICE PAYMENT FAILED
def handle_invoice_payment_failed(invoice):
    customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")

    if not customer_id or not subscription_id:
        return

    try:
        organisation = Organisation.objects.get(stripe_customer_id=customer_id)
        local_subscription = OrganisationSubscription.objects.get(
            organisation=organisation,
            stripe_subscription_id=subscription_id,
        )
    except (Organisation.DoesNotExist, OrganisationSubscription.DoesNotExist):
        return

    invoice_payments = stripe.InvoicePayment.list(invoice=invoice["id"])
    payment_intent_id = None
    for invoice_payment in invoice_payments.data:
        payment = invoice_payment.payment
        if payment and payment.type == "payment_intent":
            payment_intent_id = payment.payment_intent
            break

    if payment_intent_id:
        PaymentTransaction.objects.filter(
            organisation=organisation,
            stripe_payment_intent_id=payment_intent_id,
        ).update(status=PaymentTransactionStatus.FAILED)

    local_subscription.status = OrganisationSubscriptionStatus.PAST_DUE
    local_subscription.save(update_fields=["status"])


# SUBSCRIPTION CANCELLED
def handle_subscription_deleted(stripe_subscription):
    subscription_id = stripe_subscription.get("id")

    try:
        local_subscription = OrganisationSubscription.objects.get(
            stripe_subscription_id=subscription_id
        )
    except OrganisationSubscription.DoesNotExist:
        return

    local_subscription.status = OrganisationSubscriptionStatus.CANCELLED
    local_subscription.cancelled_at = django_timezone.now()
    local_subscription.save(update_fields=["status", "cancelled_at"])


# SUBSCRIPTION UPDATED
def handle_subscription_updated(stripe_subscription):
    subscription_id = stripe_subscription.get("id")

    try:
        local_subscription = OrganisationSubscription.objects.get(
            stripe_subscription_id=subscription_id
        )
    except OrganisationSubscription.DoesNotExist:
        return

    items = stripe_subscription.get("items", {}).get("data", [])

    update_fields = ["auto_renew"]

    local_subscription.auto_renew = not stripe_subscription.get(
        "cancel_at_period_end", False
    )

    if items:
        current_period_end = items[0].get("current_period_end")

        if current_period_end:
            period_end = datetime.fromtimestamp(
                current_period_end,
                tz=timezone.utc,
            )

            local_subscription.end_date = period_end
            local_subscription.next_billing_date = period_end

            update_fields.extend([
                "end_date",
                "next_billing_date",
            ])

    if items:
        stripe_price_id = items[0].get("price", {}).get("id")

        if (
            stripe_price_id
            and stripe_price_id != local_subscription.plan.stripe_price_id
        ):
            try:
                new_plan = SubscriptionPlan.objects.get(
                    stripe_price_id=stripe_price_id
                )

                local_subscription.plan = new_plan
                update_fields.append("plan")

            except SubscriptionPlan.DoesNotExist:
                pass

    stripe_status = stripe_subscription.get("status")

    status_map = {
        "active": OrganisationSubscriptionStatus.ACTIVE,
        "past_due": OrganisationSubscriptionStatus.PAST_DUE,
        "canceled": OrganisationSubscriptionStatus.CANCELLED,
        "unpaid": OrganisationSubscriptionStatus.PAST_DUE,
    }

    if stripe_status in status_map:
        local_subscription.status = status_map[stripe_status]
        update_fields.append("status")

    local_subscription.save(
        update_fields=list(set(update_fields))
    )
