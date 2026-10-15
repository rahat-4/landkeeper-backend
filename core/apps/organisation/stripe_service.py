import re

import stripe
from django.core.mail import send_mail
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


class PlanDowngradeBlockedError(Exception):
    def __init__(self, current_property_count, max_properties, excess):
        self.current_property_count = current_property_count
        self.max_properties = max_properties
        self.excess = excess
        super().__init__("Too many properties for this plan.")


# STRIPE OBJECT SAFE ACCESSOR
def _stripe_get(obj, key, default=None):
    try:
        return obj[key]
    except (KeyError, TypeError):
        return default


def _sync_account_credit(organisation, customer_id=None):
    customer_id = customer_id or organisation.stripe_customer_id

    if not customer_id:
        return organisation.account_credit

    customer = stripe.Customer.retrieve(customer_id)

    # Stripe: negative balance = credit owed TO the customer
    credit_pence = -customer.balance if customer.balance < 0 else 0
    credit = Decimal(credit_pence) / Decimal("100")

    if credit != organisation.account_credit:
        organisation.account_credit = credit
        organisation.save(update_fields=["account_credit"])

    return organisation.account_credit


# STRIPE CUSTOMER
def get_or_create_stripe_customer(organisation, user):
    with transaction.atomic():
        organisation = Organisation.objects.select_for_update().get(pk=organisation.pk)

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
        organisation.save(update_fields=["stripe_customer_id"])
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
        raise ValueError(f"Subscription plan '{plan.name}' has no monthly price.")

    amount = int(Decimal(plan.monthly_price) * Decimal("100"))

    price = stripe.Price.create(
        product=product_id,
        currency="gbp",
        unit_amount=amount,
        # recurring={
        #     "interval": "month",
        # },
        recurring={"interval": "day"},
        metadata={
            "plan_id": str(plan.id),
        },
    )

    plan.stripe_price_id = price.id

    plan.save(update_fields=["stripe_price_id"])

    return price.id


# STRIPE COUPON
def get_or_create_stripe_coupon(affonso_coupon):
    """
    Create (once) a coupon in our Stripe account matching the discount of
    an Affonso affiliate coupon, so Stripe charges the discounted price.
    """
    discount_type = affonso_coupon.get("discount_type")
    discount_value = Decimal(str(affonso_coupon.get("discount_value") or 0))
    duration = affonso_coupon.get("duration") or "forever"
    duration_in_months = affonso_coupon.get("duration_in_months")

    # Encode the discount in the id so a changed discount gets a new coupon
    coupon_id = re.sub(
        r"[^A-Za-z0-9_-]",
        "",
        f"affonso-{affonso_coupon['code']}-{discount_type}-{discount_value}"
        f"-{duration}-{duration_in_months or 0}",
    )

    try:
        return stripe.Coupon.retrieve(coupon_id).id
    except stripe.error.InvalidRequestError:
        pass

    coupon_params = {
        "id": coupon_id,
        "name": f"{affonso_coupon['code']} affiliate discount",
        "duration": duration,
        "metadata": {
            "affonso_coupon_code": affonso_coupon["code"],
            "affonso_affiliate_id": affonso_coupon.get("affiliate_id") or "",
        },
    }

    if discount_type == "percentage":
        coupon_params["percent_off"] = float(discount_value)
    else:
        coupon_params["amount_off"] = int(discount_value * Decimal("100"))
        coupon_params["currency"] = "gbp"

    if duration == "repeating":
        coupon_params["duration_in_months"] = duration_in_months

    print("ffffffffffffffffffffffffffffffffff")

    return stripe.Coupon.create(**coupon_params).id


# PAYMENT METHOD
def attach_payment_method(
    customer_id,
    payment_method_id,
    set_default=True,
):

    payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

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
        raise ValueError("Organisation does not have a Stripe customer.")

    payment_method = attach_payment_method(
        customer_id=customer_id,
        payment_method_id=payment_method_id,
        set_default=set_default,
    )

    card = payment_method.card

    if not card:
        raise ValueError("The Stripe PaymentMethod does not contain card information.")

    with transaction.atomic():

        if set_default:
            PaymentCard.objects.filter(
                organisation=organisation,
                is_default=True,
            ).update(is_default=False)

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


# SYNC CARD FROM PAYMENT METHOD
def _sync_card_from_payment_method(organisation, payment_method):
    if not payment_method:
        return

    payment_method_id = (
        payment_method
        if isinstance(payment_method, str)
        else _stripe_get(payment_method, "id")
    )

    if not payment_method_id:
        return

    payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
    card = payment_method.card

    if not card:
        return

    with transaction.atomic():

        PaymentCard.objects.filter(
            organisation=organisation,
            is_default=True,
        ).exclude(
            stripe_payment_method_id=payment_method.id
        ).update(is_default=False)

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


# CREATE SUBSCRIPTION DIRECTLY
def create_subscription_with_client_secret(
    organisation,
    user,
    plan,
    payment_method_id=None,
    idempotency_key=None,
    affonso_coupon=None,
):
    current = getattr(organisation, "subscription", None)

    # reuse existing pending/trialing subscription for the SAME plan
    existing = (
        current
        if (
            current
            and current.plan_id == plan.id
            and current.status
            in [
                OrganisationSubscriptionStatus.PENDING,
                OrganisationSubscriptionStatus.TRIALING,
            ]
        )
        else None
    )

    # A coupon has to be applied on a fresh subscription, so skip reuse
    if existing and existing.stripe_subscription_id and not affonso_coupon:
        try:
            stripe_subscription = stripe.Subscription.retrieve(
                existing.stripe_subscription_id,
                expand=["latest_invoice.confirmation_secret", "pending_setup_intent"],
            )

            if stripe_subscription.status == "incomplete":
                confirmation_secret = (
                    stripe_subscription.latest_invoice.confirmation_secret
                )
                if confirmation_secret:
                    return {
                        "subscription_id": stripe_subscription.id,
                        "client_secret": confirmation_secret.client_secret,
                        "mode": "payment",
                    }

            elif stripe_subscription.status == "trialing":
                setup_intent = stripe_subscription.pending_setup_intent
                if setup_intent and setup_intent.status == "requires_payment_method":
                    return {
                        "subscription_id": stripe_subscription.id,
                        "client_secret": setup_intent.client_secret,
                        "mode": "setup",
                    }

        except stripe.error.InvalidRequestError:
            pass

    if current and current.stripe_subscription_id:
        try:
            stripe.Subscription.cancel(current.stripe_subscription_id)
        except stripe.error.InvalidRequestError:
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

    # Only ever true the very first time this organisation subscribes
    give_trial = not organisation.has_used_trial

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
            "pending_setup_intent",
        ],
    }

    # if give_trial:
    #     subscription_params["trial_period_days"] = 7
    #     subscription_params["trial_settings"] = {
    #         "end_behavior": {"missing_payment_method": "cancel"},
    #     }

    if give_trial:
        from datetime import timedelta

        trial_end_timestamp = int(
            (django_timezone.now() + timedelta(minutes=2)).timestamp()
        )
        subscription_params["trial_end"] = trial_end_timestamp
        subscription_params["trial_settings"] = {
            "end_behavior": {"missing_payment_method": "cancel"},
        }

    if payment_method_id:
        subscription_params["default_payment_method"] = payment_method_id

    if affonso_coupon:
        subscription_params["discounts"] = [
            {"coupon": get_or_create_stripe_coupon(affonso_coupon)}
        ]
        subscription_params["metadata"].update(
            {
                "affonso_coupon_code": affonso_coupon["code"],
                "affonso_affiliate_id": affonso_coupon.get("affiliate_id") or "",
            }
        )

    if idempotency_key:
        stripe_subscription = stripe.Subscription.create(
            **subscription_params,
            idempotency_key=idempotency_key,
        )
    else:
        stripe_subscription = stripe.Subscription.create(
            **subscription_params,
        )

    local_status = (
        OrganisationSubscriptionStatus.TRIALING
        if give_trial
        else OrganisationSubscriptionStatus.PENDING
    )

    # LOCAL SUBSCRIPTION
    local_subscription, _ = OrganisationSubscription.objects.update_or_create(
        organisation=organisation,
        defaults={
            "plan": plan,
            "status": local_status,
            "stripe_subscription_id": stripe_subscription.id,
            "auto_renew": True,
            "trial_end_date": (
                datetime.fromtimestamp(stripe_subscription.trial_end, tz=timezone.utc)
                if give_trial and stripe_subscription.trial_end
                else None
            ),
        },
    )

    if give_trial:
        setup_intent = stripe_subscription.pending_setup_intent

        return {
            "subscription_id": stripe_subscription.id,
            "client_secret": setup_intent.client_secret,
            "mode": "setup",
        }

    # GET PAYMENT INTENT ID
    invoice = stripe.Invoice.retrieve(stripe_subscription.latest_invoice.id)

    invoice_payments = stripe.InvoicePayment.list(invoice=invoice.id)

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
                "plan_name_snapshot": plan.name,
            },
        )

    # RESPONSE
    return {
        "subscription_id": stripe_subscription.id,
        "client_secret": (
            stripe_subscription.latest_invoice.confirmation_secret.client_secret
        ),
        "mode": "payment",
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
        organisation = Organisation.objects.get(stripe_customer_id=customer_id)

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
    payment_transaction.status = PaymentTransactionStatus.SUCCEEDED

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

    payment_transaction.save(update_fields=update_fields)

    # SAVE PAYMENT CARD
    payment_method_id = payment_intent.payment_method

    if payment_method_id:
        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

        card = payment_method.card

        if card:
            with transaction.atomic():

                # Remove old default card
                PaymentCard.objects.filter(
                    organisation=organisation,
                    is_default=True,
                ).exclude(stripe_payment_method_id=payment_method.id).update(
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
        organisation = Organisation.objects.get(stripe_customer_id=customer_id)

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
        organisation = Organisation.objects.get(stripe_customer_id=customer_id)
    except Organisation.DoesNotExist:
        return None

    try:
        payment_transaction = PaymentTransaction.objects.select_related(
            "subscription"
        ).get(
            organisation=organisation,
            stripe_payment_intent_id=payment_intent_id,
        )
    except PaymentTransaction.DoesNotExist:
        return None

    payment_transaction.amount = Decimal(payment_intent.amount) / Decimal("100")

    payment_transaction.currency = payment_intent.currency.upper()

    payment_transaction.save(
        update_fields=[
            "amount",
            "currency",
        ]
    )

    return payment_transaction


# SUBSCRIPTION PLAN CHANGE
def change_subscription_plan(organisation, new_plan):
    organisation_subscription = getattr(organisation, "subscription", None)

    if (
        not organisation_subscription
        or not organisation_subscription.stripe_subscription_id
    ):
        raise ValueError("Organisation has no active Stripe subscription.")

    old_plan = organisation_subscription.plan
    is_upgrade = new_plan.monthly_price > old_plan.monthly_price

    if not is_upgrade:
        current_count = organisation.organisation_properties.count()
        if new_plan.max_properties < current_count:
            raise PlanDowngradeBlockedError(
                current_property_count=current_count,
                max_properties=new_plan.max_properties,
                excess=current_count - new_plan.max_properties,
            )

    price_id = get_or_create_stripe_price(new_plan)

    stripe_subscription = stripe.Subscription.retrieve(
        organisation_subscription.stripe_subscription_id
    )
    subscription_item_id = stripe_subscription["items"]["data"][0]["id"]

    # trial run its full remaining course untouched.
    is_trialing = stripe_subscription.status == "trialing"

    modify_kwargs = {
        "items": [{"id": subscription_item_id, "price": price_id}],
        "proration_behavior": "create_prorations" if is_upgrade else "none",
        "metadata": {
            "organisation_id": str(organisation.id),
            "plan_id": str(new_plan.id),
        },
    }

    if not is_trialing:
        modify_kwargs["billing_cycle_anchor"] = "now"

    updated_subscription = stripe.Subscription.modify(
        organisation_subscription.stripe_subscription_id,
        **modify_kwargs,
    )

    organisation_subscription.plan = new_plan
    update_fields = ["plan"]

    # existing trial_end_date/next_billing_date stay untouched.
    if not is_trialing:
        items = updated_subscription["items"]["data"]
        if items:
            current_period_start = _stripe_get(items[0], "current_period_start")
            current_period_end = _stripe_get(items[0], "current_period_end")

            if current_period_start:
                organisation_subscription.start_date = datetime.fromtimestamp(
                    current_period_start, tz=timezone.utc
                )
                update_fields.append("start_date")

            if current_period_end:
                period_end = datetime.fromtimestamp(current_period_end, tz=timezone.utc)
                organisation_subscription.end_date = period_end
                organisation_subscription.next_billing_date = period_end
                update_fields += ["end_date", "next_billing_date"]

    organisation_subscription.save(update_fields=update_fields)

    invoice = None
    requires_action = False
    payment_client_secret = None

    # trial there's nothing to charge yet.
    if not is_trialing:
        invoice = stripe.Invoice.create(
            customer=stripe_subscription.customer,
            subscription=organisation_subscription.stripe_subscription_id,
            auto_advance=False,
        )
        invoice = stripe.Invoice.finalize_invoice(invoice.id)

        invoice_payments = stripe.InvoicePayment.list(invoice=invoice.id)
        payment_intent_id = None
        for ip in invoice_payments.data:
            payment = ip.payment
            if payment and payment.type == "payment_intent":
                payment_intent_id = payment.payment_intent
                break

        if payment_intent_id:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            if payment_intent.status == "requires_action":
                requires_action = True
                payment_client_secret = payment_intent.client_secret

    account_credit = _sync_account_credit(organisation, stripe_subscription.customer)

    return {
        "is_upgrade": is_upgrade,
        "invoice": invoice,
        "account_credit": account_credit,
        "requires_action": requires_action,
        "client_secret": payment_client_secret,
    }


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

    return stripe.Subscription.retrieve(stripe_subscription_id)


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
        raise ValueError("Payment card does not belong to this organisation.")

    customer_id = organisation.stripe_customer_id

    if not customer_id:
        raise ValueError("Organisation does not have a Stripe customer.")

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
        PaymentCard.objects.filter(
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
            "default_payment_method": (new_default_card.stripe_payment_method_id),
        },
    )

    # Make it default in local DB
    new_default_card.is_default = True
    new_default_card.save(update_fields=["is_default"])


# SET DEFAULT PAYMENT METHOD
def set_default_payment_method(
    organisation,
    payment_card,
):
    if payment_card.organisation_id != organisation.id:
        raise ValueError("Payment card does not belong to this organisation.")

    customer_id = organisation.stripe_customer_id

    if not customer_id:
        raise ValueError("Organisation does not have a Stripe customer.")

    stripe.Customer.modify(
        customer_id,
        invoice_settings={
            "default_payment_method": (payment_card.stripe_payment_method_id),
        },
    )

    with transaction.atomic():

        PaymentCard.objects.filter(
            organisation=organisation,
            is_default=True,
        ).update(is_default=False)

        payment_card.is_default = True

        payment_card.save(update_fields=["is_default"])

    return payment_card


# INVOICE PAYMENT SUCCEEDED
def handle_invoice_payment_succeeded(invoice):
    customer_id = _stripe_get(invoice, "customer")

    subscription_id = _stripe_get(invoice, "subscription")
    if not subscription_id:
        parent = _stripe_get(invoice, "parent") or {}
        subscription_details = _stripe_get(parent, "subscription_details") or {}
        subscription_id = _stripe_get(subscription_details, "subscription")

    if not customer_id or not subscription_id:
        return

    try:
        organisation = Organisation.objects.get(stripe_customer_id=customer_id)
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

    # with an explicit payment_method.
    actual_payment_method = None
    if payment_intent_id:
        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        actual_payment_method = payment_intent.payment_method

    amount_paid = Decimal(_stripe_get(invoice, "amount_paid", 0)) / Decimal("100")

    is_trial_conversion = (not organisation.has_used_trial) and amount_paid > 0

    if amount_paid <= 0:
        stripe_subscription = stripe.Subscription.retrieve(subscription_id)

        pm_id = actual_payment_method or stripe_subscription.default_payment_method
        pm_id_str = pm_id if isinstance(pm_id, str) else (pm_id.id if pm_id else None)
        card_obj = (
            PaymentCard.objects.filter(stripe_payment_method_id=pm_id_str).first()
            if pm_id_str
            else None
        )

        PaymentTransaction.objects.get_or_create(
            organisation=organisation,
            stripe_invoice_id=_stripe_get(invoice, "id"),
            defaults={
                "subscription": local_subscription,
                "amount": amount_paid,
                "currency": _stripe_get(invoice, "currency", "gbp").upper(),
                "status": PaymentTransactionStatus.SUCCEEDED,
                "attempt_number": 1,
                "invoice_pdf_url": _stripe_get(invoice, "invoice_pdf"),
                "plan_name_snapshot": local_subscription.plan.name,
                "card": card_obj,
            },
        )

        # with nothing to charge won't have a payment_intent at all).
        _sync_card_from_payment_method(
            organisation,
            actual_payment_method or stripe_subscription.default_payment_method,
        )

        _sync_account_credit(organisation, customer_id)
        return

    lookup = (
        {"stripe_payment_intent_id": payment_intent_id}
        if payment_intent_id
        else {"stripe_invoice_id": _stripe_get(invoice, "id")}
    )

    stripe_subscription = stripe.Subscription.retrieve(subscription_id)

    pm_id = actual_payment_method or stripe_subscription.default_payment_method
    pm_id_str = pm_id if isinstance(pm_id, str) else (pm_id.id if pm_id else None)
    card_obj = (
        PaymentCard.objects.filter(stripe_payment_method_id=pm_id_str).first()
        if pm_id_str
        else None
    )

    with transaction.atomic():
        payment_transaction, created = PaymentTransaction.objects.get_or_create(
            organisation=organisation,
            **lookup,
            defaults={
                "subscription": local_subscription,
                "amount": amount_paid,
                "currency": _stripe_get(invoice, "currency", "gbp").upper(),
                "status": PaymentTransactionStatus.SUCCEEDED,
                "attempt_number": 1,
                "stripe_invoice_id": _stripe_get(invoice, "id"),
                "invoice_pdf_url": _stripe_get(invoice, "invoice_pdf"),
                "stripe_payment_intent_id": payment_intent_id,
                "plan_name_snapshot": local_subscription.plan.name,
                "card": card_obj,
            },
        )

        if not created:
            payment_transaction.status = PaymentTransactionStatus.SUCCEEDED
            payment_transaction.amount = amount_paid
            payment_transaction.stripe_invoice_id = _stripe_get(invoice, "id")
            payment_transaction.invoice_pdf_url = _stripe_get(invoice, "invoice_pdf")
            payment_transaction.card = card_obj
            payment_transaction.save(
                update_fields=[
                    "status",
                    "amount",
                    "stripe_invoice_id",
                    "invoice_pdf_url",
                    "card",
                ]
            )

    # subscription default.
    _sync_card_from_payment_method(
        organisation,
        actual_payment_method or stripe_subscription.default_payment_method,
    )

    # most recently used.
    if actual_payment_method:
        actual_pm_id = (
            actual_payment_method
            if isinstance(actual_payment_method, str)
            else actual_payment_method.id
        )
        if actual_pm_id != stripe_subscription.default_payment_method:
            stripe.Subscription.modify(
                subscription_id,
                default_payment_method=actual_pm_id,
            )
            stripe.Customer.modify(
                customer_id,
                invoice_settings={"default_payment_method": actual_pm_id},
            )

    invoice_line = invoice["lines"]["data"][0] if invoice["lines"]["data"] else None

    period_end_ts = None
    if invoice_line:
        period_data = _stripe_get(invoice_line, "period") or {}
        period_end_ts = _stripe_get(period_data, "end")

    if period_end_ts is None:
        subscription_item = stripe_subscription.items.data[0]
        period_end_ts = subscription_item.current_period_end

    local_subscription.status = OrganisationSubscriptionStatus.ACTIVE

    subscription_item = stripe_subscription.items.data[0]
    local_subscription.start_date = datetime.fromtimestamp(
        subscription_item.current_period_start,
        tz=timezone.utc,
    )

    local_subscription.end_date = datetime.fromtimestamp(
        period_end_ts,
        tz=timezone.utc,
    )
    local_subscription.next_billing_date = datetime.fromtimestamp(
        period_end_ts,
        tz=timezone.utc,
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

    _sync_account_credit(organisation, customer_id)

    if is_trial_conversion:
        organisation.has_used_trial = True
        organisation.save(update_fields=["has_used_trial"])

        send_trial_converted_email(
            organisation=organisation,
            amount=amount_paid,
            plan=local_subscription.plan,
        )


# INVOICE PAYMENT FAILED
def handle_invoice_payment_failed(invoice):
    customer_id = _stripe_get(invoice, "customer")

    subscription_id = _stripe_get(invoice, "subscription")
    if not subscription_id:
        parent = _stripe_get(invoice, "parent") or {}
        subscription_details = _stripe_get(parent, "subscription_details") or {}
        subscription_id = _stripe_get(subscription_details, "subscription")

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

    # Capture BEFORE overwriting status below
    was_trialing = local_subscription.status == OrganisationSubscriptionStatus.TRIALING

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

    if was_trialing:
        send_trial_payment_failed_email(organisation)
    else:
        send_renewal_payment_failed_email(organisation)


# SUBSCRIPTION CANCELLED
def handle_subscription_deleted(stripe_subscription):
    subscription_id = _stripe_get(stripe_subscription, "id")

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
    subscription_id = _stripe_get(stripe_subscription, "id")

    try:
        local_subscription = OrganisationSubscription.objects.get(
            stripe_subscription_id=subscription_id
        )
    except OrganisationSubscription.DoesNotExist:
        return

    stripe_status = _stripe_get(stripe_subscription, "status")

    if stripe_status == "active":
        try:
            latest_invoice_id = _stripe_get(stripe_subscription, "latest_invoice")
            if latest_invoice_id:
                invoice = stripe.Invoice.retrieve(latest_invoice_id)
                if invoice.status == "draft":
                    invoice = stripe.Invoice.finalize_invoice(latest_invoice_id)
                if invoice.status == "open" and invoice.amount_due > 0:
                    stripe.Invoice.pay(latest_invoice_id)
        except stripe.error.StripeError:
            pass

    default_pm = _stripe_get(stripe_subscription, "default_payment_method")
    if default_pm:
        _sync_card_from_payment_method(local_subscription.organisation, default_pm)

    items_data = _stripe_get(stripe_subscription, "items") or {}
    items = _stripe_get(items_data, "data", [])

    update_fields = ["auto_renew"]

    local_subscription.auto_renew = not _stripe_get(
        stripe_subscription, "cancel_at_period_end", False
    )

    # before invoice.payment_succeeded ever set it)
    if not local_subscription.start_date:
        stripe_start = _stripe_get(stripe_subscription, "start_date")

        if stripe_start:
            local_subscription.start_date = datetime.fromtimestamp(
                stripe_start,
                tz=timezone.utc,
            )
            update_fields.append("start_date")

    if items:
        current_period_end = _stripe_get(items[0], "current_period_end")

        if current_period_end:
            period_end = datetime.fromtimestamp(
                current_period_end,
                tz=timezone.utc,
            )

            local_subscription.end_date = period_end
            local_subscription.next_billing_date = period_end

            update_fields.extend(
                [
                    "end_date",
                    "next_billing_date",
                ]
            )

    if items:
        price = _stripe_get(items[0], "price") or {}
        stripe_price_id = _stripe_get(price, "id")

        if (
            stripe_price_id
            and stripe_price_id != local_subscription.plan.stripe_price_id
        ):
            try:
                new_plan = SubscriptionPlan.objects.get(stripe_price_id=stripe_price_id)

                local_subscription.plan = new_plan
                update_fields.append("plan")

            except SubscriptionPlan.DoesNotExist:
                pass

    status_map = {
        "trialing": OrganisationSubscriptionStatus.TRIALING,
        "active": OrganisationSubscriptionStatus.ACTIVE,
        "past_due": OrganisationSubscriptionStatus.PAST_DUE,
        "canceled": OrganisationSubscriptionStatus.CANCELLED,
        "unpaid": OrganisationSubscriptionStatus.PAST_DUE,
    }

    if stripe_status in status_map:
        new_status = status_map[stripe_status]
        local_subscription.status = new_status
        update_fields.append("status")

        if (
            new_status != OrganisationSubscriptionStatus.CANCELLED
            and local_subscription.cancelled_at
        ):
            local_subscription.cancelled_at = None
            update_fields.append("cancelled_at")

    local_subscription.save(update_fields=list(set(update_fields)))


# EMAIL NOTIFICATIONS
def _resolve_billing_email(organisation):
    organisation_user = (
        organisation.organisation_users.select_related("user")
        .order_by("created_at")
        .first()
    )

    return organisation_user.user.email if organisation_user else None


def send_trial_converted_email(organisation, amount, plan):
    billing_email = _resolve_billing_email(organisation)

    if not billing_email:
        return

    send_mail(
        subject="Your free trial has ended — payment received",
        message=(
            f"We've charged your card £{amount} for the {plan.name} plan. "
            f"Thanks for staying with us!"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[billing_email],
    )


def send_trial_payment_failed_email(organisation):
    billing_email = _resolve_billing_email(organisation)

    if not billing_email:
        return

    send_mail(
        subject="We couldn't charge your card after your free trial",
        message=(
            "Your 7-day free trial has ended and we were unable to charge "
            "your card. Please add a valid payment method to keep access "
            "to the platform."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[billing_email],
    )


def send_renewal_payment_failed_email(organisation):
    billing_email = _resolve_billing_email(organisation)

    if not billing_email:
        return

    send_mail(
        subject="Your subscription payment failed",
        message=(
            "We were unable to charge your card for this month's "
            "subscription renewal. Please update your payment method to "
            "avoid losing access to the platform."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[billing_email],
    )


# SCHEDULE A PLAN DOWNGRADE FOR NEXT BILLING CYCLE
def schedule_plan_downgrade(organisation, new_plan):
    organisation_subscription = getattr(organisation, "subscription", None)

    if (
        not organisation_subscription
        or not organisation_subscription.stripe_subscription_id
    ):
        raise ValueError("Organisation has no active Stripe subscription.")

    current_count = organisation.organisation_properties.count()
    if new_plan.max_properties < current_count:
        excess = current_count - new_plan.max_properties
        raise PlanDowngradeBlockedError(
            current_property_count=current_count,
            max_properties=new_plan.max_properties,
            excess=excess,
        )

    new_price_id = get_or_create_stripe_price(new_plan)

    stripe_subscription = stripe.Subscription.retrieve(
        organisation_subscription.stripe_subscription_id
    )
    current_item = stripe_subscription["items"]["data"][0]
    current_price_id = current_item["price"]["id"]
    current_period_start = current_item["current_period_start"]
    current_period_end = current_item["current_period_end"]
    schedule = stripe.SubscriptionSchedule.create(
        from_subscription=organisation_subscription.stripe_subscription_id,
    )

    stripe.SubscriptionSchedule.modify(
        schedule.id,
        end_behavior="release",
        phases=[
            {
                "items": [{"price": current_price_id, "quantity": 1}],
                "start_date": current_period_start,
                "end_date": current_period_end,
                "proration_behavior": "none",
            },
            {
                "items": [{"price": new_price_id, "quantity": 1}],
                "start_date": current_period_end,
                "proration_behavior": "none",
            },
        ],
    )

    effective_date = datetime.fromtimestamp(current_period_end, tz=timezone.utc)

    organisation_subscription.pending_plan = new_plan
    organisation_subscription.pending_plan_effective_date = effective_date
    organisation_subscription.stripe_schedule_id = schedule.id
    organisation_subscription.save(
        update_fields=[
            "pending_plan",
            "pending_plan_effective_date",
            "stripe_schedule_id",
        ]
    )

    return {
        "detail": (
            f"Your plan will switch to {new_plan.name} on "
            f"{effective_date.date()}. You'll keep your current plan "
            f"and won't be charged until then."
        ),
        "effective_date": effective_date.isoformat(),
        "pending_plan": new_plan.name,
    }


def get_pending_downgrade_info(organisation_subscription):
    if not organisation_subscription.stripe_schedule_id:
        return None

    try:
        schedule = stripe.SubscriptionSchedule.retrieve(
            organisation_subscription.stripe_schedule_id
        )
    except stripe.error.InvalidRequestError:
        return None

    if schedule.status != "active" or len(schedule.phases) < 2:
        return None

    next_phase = schedule.phases[1]
    price_id = next_phase["items"][0]["price"]
    try:
        pending_plan = SubscriptionPlan.objects.get(stripe_price_id=price_id)
    except SubscriptionPlan.DoesNotExist:
        return None

    return {
        "plan": pending_plan,
        "effective_date": datetime.fromtimestamp(
            next_phase["start_date"], tz=timezone.utc
        ),
    }


def cancel_pending_downgrade(organisation):
    organisation_subscription = getattr(organisation, "subscription", None)

    if (
        not organisation_subscription
        or not organisation_subscription.stripe_schedule_id
    ):
        raise ValueError("No pending plan change to remove.")

    try:
        stripe.SubscriptionSchedule.release(
            organisation_subscription.stripe_schedule_id
        )
    except stripe.error.InvalidRequestError as e:
        raise ValueError(f"Could not remove the pending plan change: {e}")

    organisation_subscription.pending_plan = None
    organisation_subscription.pending_plan_effective_date = None
    organisation_subscription.stripe_schedule_id = None
    organisation_subscription.save(
        update_fields=[
            "pending_plan",
            "pending_plan_effective_date",
            "stripe_schedule_id",
        ]
    )

    return {
        "detail": "Your scheduled plan change has been removed. You're staying on your current plan."
    }
