import logging
import stripe
from django.conf import settings

from apps.organisation.models import Organisation

logger = logging.getLogger("apps.organisation.stripe_connect")
stripe.api_key = settings.STRIPE_SECRET_KEY


def get_oauth_authorize_url(organisation):
    return (
        "https://connect.stripe.com/oauth/authorize"
        f"?response_type=code"
        f"&client_id={settings.STRIPE_CONNECT_CLIENT_ID}"
        f"&scope=read_write"
        f"&state={organisation.id}"
        f"&redirect_uri={settings.FRONTEND_URL}/settings/payments/oauth-callback"
    )


def exchange_oauth_code(code):
    return stripe.OAuth.token(grant_type="authorization_code", code=code)


def save_oauth_result(organisation, oauth_response):
    organisation.stripe_account_id = oauth_response.stripe_user_id
    organisation.stripe_publishable_key = oauth_response.stripe_publishable_key
    organisation.set_stripe_access_token(oauth_response.access_token)
    organisation.save(
        update_fields=[
            "stripe_account_id",
            "stripe_publishable_key",
            "stripe_access_token_encrypted",
        ]
    )
    sync_account_status_from_stripe(organisation)


def sync_account_status_from_stripe(organisation):
    account = stripe.Account.retrieve(organisation.stripe_account_id)
    organisation.stripe_charges_enabled = account.charges_enabled
    organisation.stripe_payouts_enabled = account.payouts_enabled
    organisation.stripe_details_submitted = account.details_submitted
    organisation.save(
        update_fields=[
            "stripe_charges_enabled",
            "stripe_payouts_enabled",
            "stripe_details_submitted",
        ]
    )
    return organisation


def sync_account_status(
    stripe_account_id, charges_enabled, payouts_enabled, details_submitted
):
    updated = Organisation.objects.filter(stripe_account_id=stripe_account_id).update(
        stripe_charges_enabled=charges_enabled,
        stripe_payouts_enabled=payouts_enabled,
        stripe_details_submitted=details_submitted,
    )
    if not updated:
        logger.warning(
            "Stripe webhook: account.updated for unknown stripe_account_id",
            extra={"stripe_account_id": stripe_account_id},
        )
    return updated
