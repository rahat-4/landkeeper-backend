from autoslug import AutoSlugField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.marketplace.utils import marketplace_provider_logo_upload_path
from common.models import CreatedAtUpdatedAtBaseModel


class MarketplaceCategory(CreatedAtUpdatedAtBaseModel):
    name = models.CharField(max_length=128, unique=True, verbose_name=_("Name"))
    slug = AutoSlugField(populate_from="name", unique=True, always_update=False)
    description = models.TextField(blank=True, null=True)
    icon = models.TextField(blank=True, null=True, verbose_name=_("Icon"))
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("Marketplace Category")
        verbose_name_plural = _("Marketplace Categories")
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class MarketplaceProvider(CreatedAtUpdatedAtBaseModel):
    name = models.CharField(max_length=255, verbose_name=_("Provider Name"))
    slug = AutoSlugField(populate_from="name", unique=True, always_update=False)
    logo = models.ImageField(
        upload_to=marketplace_provider_logo_upload_path, blank=True, null=True
    )
    short_description = models.CharField(max_length=500, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    services_offered = models.JSONField(default=list, blank=True)
    website_url = models.URLField(max_length=500, blank=True, null=True)
    referral_url = models.URLField(max_length=500, blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    contact_phone = models.CharField(max_length=32, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    # M2M
    categories = models.ManyToManyField(
        MarketplaceCategory, related_name="providers", blank=True
    )

    class Meta:
        verbose_name = _("Marketplace Provider")
        verbose_name_plural = _("Marketplace Providers")
        ordering = ["-is_featured", "display_order", "name"]

    def __str__(self):
        return self.name

    @property
    def outbound_url(self):
        """Referral link takes priority so landlords are tracked through it."""
        return self.referral_url or self.website_url
