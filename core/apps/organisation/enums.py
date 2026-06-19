from django.db import models
from django.utils.translation import gettext_lazy as _


class GenderChoices(models.TextChoices):
    MALE = "MALE", _("Male")
    FEMALE = "FEMALE", _("Female")
    OTHER = "OTHER", _("Other")


class OrganisationRoleChoices(models.TextChoices):
    LANDLORD = "LANDLORD", _("Landlord")
    ADMIN = "ADMIN", _("Admin")
    LETTING_AGENT = "LETTING_AGENT", _("Letting Agent")


class SourceChoices(models.TextChoices):
    GOOGLE = "GOOGLE", _("Google")
    SOCIAL_MEDIA = "SOCIAL_MEDIA", _("Social Media")
    REFERRAL = "REFERRAL", _("Referral")
    WEBSITE = "WEBSITE", _("Website")
    OTHER = "OTHER", _("Other")
