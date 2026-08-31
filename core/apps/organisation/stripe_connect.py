import logging
import stripe
from django.conf import settings

from apps.organisation.models import Organisation

logger = logging.getLogger("apps.organisation.stripe_connect")
stripe.api_key = settings.STRIPE_SECRET_KEY


def create_connect_account(organisation, email):
    account = stripe.Account.create(
        type="express",
        country="GB",
        email=email,
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        business_type="company",
        metadata={"organisation_id": str(organisation.id)},
    )
    organisation.stripe_account_id = account.id
    organisation.save(update_fields=["stripe_account_id"])
    return account


def create_account_link(organisation):
    if not organisation.stripe_account_id:
        raise ValueError("Organisation has no Stripe account yet")
    return stripe.AccountLink.create(
        account=organisation.stripe_account_id,
        refresh_url=f"{settings.FRONTEND_URL}/settings/payments/refresh",
        return_url=f"{settings.FRONTEND_URL}/settings/payments/complete",
        type="account_onboarding",
    )


def sync_account_status(stripe_account_id, charges_enabled, payouts_enabled, details_submitted):
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