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
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["display_order", "id"]

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
    max_users = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of users. Leave empty for unlimited.",
    )
    # referral_discount_percent = models.DecimalField(
    #     max_digits=5,
    #     decimal_places=2,
    #     default=20.00,
    # )
    is_active = models.BooleanField(default=True)
    description = models.TextField(
        blank=True,
        null=True,
    )
    features = models.ManyToManyField(
        SubscriptionFeature,
        through="SubscriptionPlanFeature",
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

    def has_feature(self, code):
        return self.plan_features.filter(
            feature__code=code,
            feature__is_active=True,
            is_included=True,
        ).exists()


class SubscriptionPlanFeature(models.Model):
    """Per-plan value of a feature, e.g. "Limited" vs "Full" for Reports."""

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.CASCADE,
        related_name="plan_features",
    )
    feature = models.ForeignKey(
        SubscriptionFeature,
        on_delete=models.CASCADE,
        related_name="plan_features",
    )
    is_included = models.BooleanField(default=True)
    value = models.CharField(
        max_length=150,
        blank=True,
        help_text="Display text, e.g. 'Up to 3' or 'Priority support'. "
        "Empty means a plain included/not-included tick.",
    )

    class Meta:
        ordering = ["feature__display_order", "feature_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "feature"],
                name="unique_feature_per_plan",
            )
        ]

    def __str__(self):
        return f"{self.plan} - {self.feature}"


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
    card = models.ForeignKey(
        "subscription.PaymentCard",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="GBP")
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
    )
    stripe_invoice_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
    )
    invoice_pdf_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentTransactionStatus.choices,
        default=PaymentTransactionStatus.PENDING,
    )
    attempt_number = models.PositiveSmallIntegerField(default=0)
    plan_name_snapshot = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.organisation} - {self.amount} {self.currency} ({self.status})"