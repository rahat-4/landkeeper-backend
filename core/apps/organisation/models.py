from apps.authentication.models import User
from django.utils.translation import gettext_lazy as _
from apps.organisation.enums import (
    GenderChoices,
    OrganisationRoleChoices,
    SourceChoices
)
from common.models import (
    NameSlugDescriptionBaseModel,
    TimestampThumbnailImageField,
    CreatedAtUpdatedAtBaseModel
)
from django.db import models

class Organisation(NameSlugDescriptionBaseModel):
    email = models.EmailField(unique=True)
    logo = TimestampThumbnailImageField(
        upload_to="organisation/logo", blank=True, null=True
    )
    profile_image = TimestampThumbnailImageField(
        upload_to="organisation/profile", blank=True, null=True
    )
    primary_mobile = models.CharField(max_length=20)
    other_contact = models.CharField(max_length=64, blank=True, null=True)
    contact_person = models.CharField(max_length=64, blank=True, null=True)
    contact_person_designation = models.CharField(max_length=64, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at", "-updated_at"]

    def __str__(self):
        return f"{self.email} - {self.name}"


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
        default=OrganisationRoleChoices.ORGANISATION_ADMIN,
        blank=True,
        null=True,
        verbose_name=_("Role"),
    )
    designation = models.CharField(
        max_length=128, blank=True, null=True, verbose_name=_("Designation")
    )
    official_email = models.EmailField(
        max_length=255, blank=True, null=True, verbose_name=_("Official Email")
    )
    official_phone = models.CharField(
        max_length=24, blank=True, null=True, verbose_name=_("Official Phone")
    )
    permanent_address = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Permanent Address")
    )
    present_address = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Present Address")
    )
    dob = models.DateField(blank=True, null=True, verbose_name=_("Date of Birth"))
    gender = models.CharField(
        max_length=10,
        choices=GenderChoices.choices,
        default=GenderChoices.MALE,
        verbose_name=_("Gender"),
    )
    joining_date = models.DateField(
        blank=True, null=True, verbose_name=_("Joining Date")
    )
    source = models.CharField(
        max_length=255,
        choices=SourceChoices.choices,
        blank=True,
        null=True,
        verbose_name=_("Source"),
    )
    other_source = models.CharField(max_length=255, blank=True, null=True)
    note = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Note"),
    )

    class Meta:
        unique_together = ("user", "organisation")
        verbose_name = _("Organisation User")
        verbose_name_plural = _("Organisation Users")
        ordering = ["-created_at", "-updated_at"]

    def __str__(self):
        return f"{self.user.email} - {self.organisation.name} ({self.role})"