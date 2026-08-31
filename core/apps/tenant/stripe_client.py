import logging

import stripe
from django.conf import settings

logger = logging.getLogger("apps.tenant.payments")

stripe.api_key = settings.STRIPE_SECRET_KEY


def create_payment_intent(
    amount,
    currency="gbp",
    customer_id=None,
    payment_method_id=None,
    idempotency_key=None,
    metadata=None,
    stripe_account_destination = None,
    application_fee_amount = None,
):

    params = {
        "amount": int(round(amount * 100)),
        "currency": currency,
        "confirm": payment_method_id is not None,
        "automatic_payment_methods": {
            "enabled": True,
            "allow_redirects": "never",
        },
        "metadata": metadata or {},
    }
    if customer_id:
        params["customer"] = customer_id
    if payment_method_id:
        params["payment_method"] = payment_method_id

    if stripe_account_destination:
        params["transfer_data"] = {"destination": stripe_account_destination}
        if application_fee_amount:
            params["application_fee_amount"] = int(application_fee_amount)

    request_options = {}
    if idempotency_key:
        request_options["idempotency_key"] = idempotency_key

    try:
        return stripe.PaymentIntent.create(**params, **request_options)
    except stripe.error.CardError:
        logger.info("Stripe card declined", extra={"idempotency_key": idempotency_key})
        raise
    except stripe.error.StripeError:
        logger.exception(
            "Stripe create_payment_intent failed",
            extra={"idempotency_key": idempotency_key},
        )
        raise