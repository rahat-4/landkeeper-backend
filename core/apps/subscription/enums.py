from django.db import models


class PlanType(models.TextChoices):
    BASIC = "BASIC", "Basic"
    STANDARD = "STANDARD", "Standard"
    PREMIUM = "PREMIUM", "Premium"


class PaymentTransactionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED", "Partially Refunded"
    REFUNDED = "REFUNDED", "Refunded"