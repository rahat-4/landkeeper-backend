from django.db import models


class PlanType(models.TextChoices):
    STARTER = "STARTER", "Starter"
    STANDARD = "STANDARD", "Standard"
    PREMIUM = "PREMIUM", "Premium"


class PaymentTransactionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    TRIALING = "TRIALING", "Trialing"
    FAILED = "FAILED", "Failed"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED", "Partially Refunded"
    REFUNDED = "REFUNDED", "Refunded"
