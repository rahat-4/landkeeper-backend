from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.organisation.enums import (
    OrganisationRoleChoices,
    OrganisationSubscriptionStatus,
)
from apps.subscription.models import SubscriptionPlan
from common.models import (
    NameSlugDescriptionBaseModel,
    TimestampThumbnailImageField,
    CreatedAtUpdatedAtBaseModel,
)

from apps.organisation.crypto import encrypt_token
from apps.organisation.crypto import decrypt_token

User = get_user_model()


class Organisation(NameSlugDescriptionBaseModel):
    logo = TimestampThumbnailImageField(
        upload_to="organisation/logo", blank=True, null=True
    )
    profile_image = TimestampThumbnailImageField(
        upload_to="organisation/profile", blank=True, null=True
    )
    primary_mobile = models.CharField(max_length=20, blank=True, null=True)
    other_contact = models.CharField(max_length=64, blank=True, null=True)
    contact_person = models.CharField(max_length=64, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    stripe_account_id = models.CharField(max_length=64, blank=True, null=True, db_index=True)
    stripe_publishable_key = models.CharField(max_length=128, blank=True, null=True)
    stripe_access_token_encrypted = models.TextField(blank=True, null=True)
    stripe_charges_enabled = models.BooleanField(default=False)
    stripe_payouts_enabled = models.BooleanField(default=False)
    stripe_details_submitted = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-updated_at"]

    def __str__(self):
        return f"{self.name}"

    def set_stripe_access_token(self, plain_token):
        self.stripe_access_token_encrypted = encrypt_token(plain_token)

    def get_stripe_access_token(self):
        return decrypt_token(self.stripe_access_token_encrypted)


class OrganisationUser(CreatedAtUpdatedAtBaseModel):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="organisation_users",
        verbose_name=_("User"),
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="organisation_users",
        verbose_name=_("Organisation"),
    )
    role = models.CharField(
        max_length=64,
        choices=OrganisationRoleChoices.choices,
        default=OrganisationRoleChoices.LANDLORD,
        blank=True,
        null=True,
        verbose_name=_("Role"),
    )

    class Meta:
        unique_together = ("user", "organisation")
        verbose_name = _("Organisation User")
        verbose_name_plural = _("Organisation Users")
        ordering = ["-created_at", "-updated_at"]

    def __str__(self):
        return f"{self.user.email} - {self.organisation.name} ({self.role})"


class OrganisationSubscription(CreatedAtUpdatedAtBaseModel):
    organisation = models.OneToOneField(
        "organisation.Organisation",
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=20,
        choices=OrganisationSubscriptionStatus.choices,
        default=OrganisationSubscriptionStatus.ACTIVE,
    )
    started_at = models.DateTimeField()
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def __str__(self):
        return f"{self.organisation} - {self.plan}"
