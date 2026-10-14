import uuid

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from apps.organisation.models import Organisation
from apps.referral.enums import (
    ReferralStatus,
    ReferralStatusChoices,
    CommissionStatusChoices,
)
from common.models import CreatedAtUpdatedAtBaseModel

User = get_user_model()


class Referral(CreatedAtUpdatedAtBaseModel):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="referral_profile"
    )
    affiliate_id = models.TextField()
    coupon_code = models.CharField(max_length=16, unique=True, editable=False)
    status = models.CharField(
        max_length=16,
        choices=ReferralStatus.choices,
        default=ReferralStatus.ACTIVE,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} ({self.get_status_display()})"
