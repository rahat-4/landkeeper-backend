from django.db import models

from django.contrib.auth import get_user_model

from common.models import CreatedAtUpdatedAtBaseModel

from .enums import PlanType
from .enums import PaymentTransactionStatus
from django.db.models import Q

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
    stripe_product_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )
    stripe_price_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["monthly_price"]

    def __str__(self):
        return self.name


class PaymentCard(CreatedAtUpdatedAtBaseModel):
    stripe_payment_method_id = models.CharField(
        max_length=255,
        unique=True,
    )
    last_four = models.CharField(max_length=4)
    card_brand = models.CharField(max_length=50)
    expiry_month = models.IntegerField()
    expiry_year = models.IntegerField()
    is_default = models.BooleanField(default=False)

    # Fk
    organisation = models.ForeignKey(
        "organisation.Organisation",
        on_delete=models.CASCADE, related_name="organisation_payment_cards"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organisation"],
                condition=Q(is_default=True),
                name="unique_default_card_per_organisation",
            )
        ]

    def __str__(self):
        return f"{self.card_brand} ending in {self.last_four}"



class PaymentTransaction(CreatedAtUpdatedAtBaseModel):
    organisation = models.ForeignKey(
        "organisation.Organisation", on_delete=models.CASCADE, related_name="payment_transactions"
    )
    subscription = models.ForeignKey(
        "organisation.OrganisationSubscription", on_delete=models.CASCADE, related_name="transactions"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="GBP")
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentTransactionStatus.choices,
        default=PaymentTransactionStatus.PENDING,
    )
    attempt_number = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.organisation} - {self.amount} {self.currency} ({self.status})"