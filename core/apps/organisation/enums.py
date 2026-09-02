from django.db import models
from django.utils.translation import gettext_lazy as _


class GenderChoices(models.TextChoices):
    MALE = "MALE", _("Male")
    FEMALE = "FEMALE", _("Female")
    OTHER = "OTHER", _("Other")


class OrganisationRoleChoices(models.TextChoices):
    LANDLORD = "LANDLORD", _("Landlord")
    ADMIN = "ADMIN", _("Admin")
    MORTGAGE_ADVISER = "MORTGAGE_ADVISER", _("Mortgage Adviser")
    LETTING_AGENT = "LETTING_AGENT", _("Letting Agent")


class SourceChoices(models.TextChoices):
    GOOGLE = "GOOGLE", _("Google")
    SOCIAL_MEDIA = "SOCIAL_MEDIA", _("Social Media")
    REFERRAL = "REFERRAL", _("Referral")
    WEBSITE = "WEBSITE", _("Website")
    OTHER = "OTHER", _("Other")


class OrganisationSubscriptionStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    ACTIVE = "ACTIVE", "Active"
    TRIALING = "TRIALING", "Trialing"
    PAST_DUE = "PAST_DUE", "Past Due"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"
