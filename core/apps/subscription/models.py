from django.db import models

from django.contrib.auth import get_user_model

from common.models import CreatedAtUpdatedAtBaseModel

from .enums import PlanType

User = get_user_model()


class SubscriptionFeature(models.Model):
    code = models.CharField(
        max_length=100,
        unique=True,
    )
    name = models.CharField(
        max_length=150,
    )
    description = models.TextField(
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class SubscriptionPlan(CreatedAtUpdatedAtBaseModel):
    name = models.CharField(max_length=50)
    plan_type = models.CharField(
        max_length=20,
        choices=PlanType.choices,
        unique=True,
        null=True,
    )
    monthly_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
    )
    max_properties = models.PositiveIntegerField()
    referral_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20.00,
    )
    is_active = models.BooleanField(default=True)
    description = models.TextField(
        blank=True,
        null=True,
    )

    features = models.ManyToManyField(
        SubscriptionFeature,
        related_name="plans",
        blank=True,
    )
    stripe_product_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_price_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["monthly_price"]

    def __str__(self):
        return self.name
