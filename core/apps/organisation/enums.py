from django.db import models
from django.utils.translation import gettext_lazy as _

class GenderChoices(models.TextChoices):
    MALE = "MALE", _("Male")
    FEMALE = "FEMALE", _("Female")
    OTHER = "OTHER", _("Other")


class OrganisationRoleChoices(models.TextChoices):
    CLIENT = "CLIENT", _("Client")
    ORGANISATION_ADVISER = "ORGANISATION_ADVISER", _("Organisation Adviser")
    ORGANISATION_DIRECTOR = "ORGANISATION_DIRECTOR", _("Organisation Director")
    ORGANISATION_ADMIN = "ORGANISATION_ADMIN", _("Organisation Admin")


class SourceChoices(models.TextChoices):
    GOOGLE = "GOOGLE", _("Google")
    SOCIAL_MEDIA = "SOCIAL_MEDIA", _("Social Media")
    REFERRAL = "REFERRAL", _("Referral")
    WEBSITE = "WEBSITE", _("Website")
    OTHER = "OTHER", _("Other")