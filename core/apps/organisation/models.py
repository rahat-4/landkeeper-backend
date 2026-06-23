from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.organisation.enums import OrganisationRoleChoices
from common.models import (
    NameSlugDescriptionBaseModel,
    TimestampThumbnailImageField,
    CreatedAtUpdatedAtBaseModel,
)

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

    class Meta:
        ordering = ["-created_at", "-updated_at"]

    def __str__(self):
        return f"{self.name}"


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
