from django.contrib.auth import get_user_model
from django.db import models

from apps.referral.enums import ReferralStatus
from apps.property.models import Tenant
from common.models import CreatedAtUpdatedAtBaseModel

User = get_user_model()


class Referral(CreatedAtUpdatedAtBaseModel):
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="referral_profile",
    )
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="tenant_referral_profile",
    )
    affiliate_id = models.TextField()
    coupon_code = models.CharField(max_length=16, unique=True)
    status = models.CharField(
        max_length=16,
        choices=ReferralStatus.choices,
        default=ReferralStatus.ACTIVE,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} ({self.get_status_display()})"
