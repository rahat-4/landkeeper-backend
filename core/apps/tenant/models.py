import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from apps.organisation.models import Organisation
from apps.property.models import Tenant, Property
from apps.tenant.enums import (
    PaymentProviderChoices,
    PaymentMethodTypeChoices,
    PaymentMethodStatusChoices,
    RentPaymentStatusChoices,
    MaintenanceCategory,
    MaintenanceStatus
)
from apps.tenant.utils import receipt_upload_path
from common.models import CreatedAtUpdatedAtBaseModel, DocumentFile


class PaymentMethod(CreatedAtUpdatedAtBaseModel):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="payment_methods"
    )
    provider = models.CharField(max_length=20, choices=PaymentProviderChoices.choices)
    method_type = models.CharField(
        max_length=20, choices=PaymentMethodTypeChoices.choices
    )
    provider_customer_id = models.CharField(max_length=128, blank=True, null=True)
    provider_mandate_id = models.CharField(max_length=128, blank=True, null=True)  # GoCardless
    provider_payment_method_id = models.CharField(
        max_length=128, blank=True, null=True
    )

    status = models.CharField(
        max_length=20,
        choices=PaymentMethodStatusChoices.choices,
        default=PaymentMethodStatusChoices.PENDING,
    )
    is_default = models.BooleanField(default=True)
    card_last4 = models.CharField(max_length=4, blank=True, null=True)
    card_brand = models.CharField(max_length=32, blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "provider", "is_default"]),
        ]

    def __str__(self):
        return f"{self.tenant} - {self.get_method_type_display()} ({self.status})"


class RentPayment(CreatedAtUpdatedAtBaseModel):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="rent_payments"
    )
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="property_rent_payments"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="organisation_rent_payments"
    )
    payment_method = models.ForeignKey(
        PaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rent_payments",
    )
    reference = models.CharField(max_length=64, unique=True, editable=False, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    paid_date = models.DateField(blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=RentPaymentStatusChoices.choices,
        default=RentPaymentStatusChoices.PENDING,
    )
    provider_payment_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    receipt_file = models.FileField(
        upload_to=receipt_upload_path, blank=True, null=True
    )
    failure_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
        ]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = f"RENT-{self.due_date:%Y%m}-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} - {self.tenant} - £{self.amount}"


class ProcessedWebhookEvent(models.Model):
    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=128)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"], name="unique_provider_event"
            )
        ]
        indexes = [
            models.Index(fields=["provider", "event_id"]),
        ]

class CardPayment(CreatedAtUpdatedAtBaseModel):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="card_payments"
    )
    payment_method = models.ForeignKey(
        PaymentMethod, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="card_payments",
    )
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    provider_payment_id = models.CharField(max_length=128, blank=True, null=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=RentPaymentStatusChoices.choices,
        default=RentPaymentStatusChoices.PENDING,
    )
    failure_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "due_date"]),
        ]

    def __str__(self):
        return f"{self.alias} - {self.tenant} - £{self.amount}"



class MaintenanceRequest(CreatedAtUpdatedAtBaseModel):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="tenant_maintenance_requests",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="property_maintenance_requests",
    )
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="organisation_maintenance_requests",
    )
    issue = models.TextField(null=True, blank=True)
    category = models.CharField(
        max_length=32,
        choices=MaintenanceCategory.choices,
        default=MaintenanceCategory.PLUMBING,
    )
    current_status = models.CharField(
        max_length=20,
        choices=MaintenanceStatus.choices,
        default=MaintenanceStatus.SUBMITTED
    )
    notes = models.TextField(null=True, blank=True)
    is_emergency = models.BooleanField(default=False)
    documents = models.ManyToManyField(
        DocumentFile,
        blank=True,
        related_name="maintenance_requests",
    )

    class Meta:
        ordering = ["-updated_at", "-created_at"]
        indexes = [
            models.Index(fields=["organisation", "tenant"]),
            models.Index(fields=["current_status"]),
        ]

    def __str__(self):
        return f"{self.get_category_display()}"


class MaintenanceRequestComment(CreatedAtUpdatedAtBaseModel):
    message = models.TextField(verbose_name=_("Message"))
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="replies",
        blank=True,
        null=True,
        verbose_name=_("Parent Comment"),
    )
    # Staff/org user author (landlord, admin, letting agent)
    staff_author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="maintenance_request_comments",
        verbose_name=_("Commented By (Staff)"),
        null=True,
        blank=True,
    )
    # Tenant author
    tenant_author = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="maintenance_request_comments",
        verbose_name=_("Commented By (Tenant)"),
        null=True,
        blank=True,
    )
    maintenance_request = models.ForeignKey(
        MaintenanceRequest,
        on_delete=models.CASCADE,
        related_name="maintenance_request_comments",
        verbose_name=_("Maintenance Request"),
    )
    documents = models.ManyToManyField(
        DocumentFile,
        blank=True,
        related_name="maintenance_request_comments",
        verbose_name=_("Attachments"),
    )

    class Meta:
        verbose_name = _("Maintenance Request Comment")
        verbose_name_plural = _("Maintenance Request Comments")
        ordering = ["-created_at", "-updated_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                        models.Q(staff_author__isnull=False, tenant_author__isnull=True)
                        | models.Q(staff_author__isnull=True, tenant_author__isnull=False)
                ),
                name="maintenance_comment_single_author",
            )
        ]

    @property
    def author(self):
        return self.staff_author or self.tenant_author

    def __str__(self):
        who = self.author.email if hasattr(self.author, "email") else str(self.author)
        return f"Comment by {who} on Maintenance #{self.maintenance_request.id}"