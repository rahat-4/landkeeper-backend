from django.db import models
from apps.organisation.models import Organisation
from common.models import CreatedAtUpdatedAtBaseModel, Media, DocumentFile
from .enums import (
    PropertyType,
    CertificateType,
    StatusType,
    ProductType,
    DocumentCategoryType,
    TransactionType,
    Category,
)
from .utils import certificate_file_upload_path, tenant_avatar_upload_path


class Property(CreatedAtUpdatedAtBaseModel):
    property_name = models.CharField(max_length=255)
    property_type = models.CharField(
        max_length=20,
        choices=PropertyType.choices,
        default=PropertyType.RESIDENTIAL,
    )
    status = models.CharField(
        max_length=50,
        choices=StatusType.choices,
        default=StatusType.OCCUPIED,
    )
    address = models.CharField(max_length=255)
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    current_value = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    purchase_date = models.DateField(blank=True, null=True)
    bedrooms = models.PositiveIntegerField(blank=True, null=True)
    bathrooms = models.PositiveIntegerField(blank=True, null=True)
    rent_per_month = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    documents = models.ManyToManyField(
        Media, blank=True, related_name="property_documents"
    )
    notes = models.TextField(blank=True, null=True)

    # Fk
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="organisation_properties"
    )

    def __str__(self):
        return self.property_name

    @property
    def current_mortgage(self):
        return (
            self.mortgages.filter(end_date__isnull=True).order_by("-start_date").first()
        )


class Mortgage(CreatedAtUpdatedAtBaseModel):
    lender_name = models.CharField(max_length=255)
    product_type = models.CharField(
        max_length=50,
        choices=ProductType.choices,
        default=ProductType.FIXED_RATE,
    )
    interest_rate = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    loan_amount = models.DecimalField(
        max_digits=12, decimal_places=2, blank=True, null=True
    )
    outstanding_balance = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    monthly_payment = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    term = models.PositiveIntegerField(blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    broker_notes = models.TextField(blank=True, null=True)

    # FK
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="property_mortgages"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="organisation_mortgages"
    )

    def __str__(self):
        return f"{self.lender_name} - {self.mortgage_account_number}"


class Tenant(CreatedAtUpdatedAtBaseModel):
    avatar = models.ImageField(
        upload_to=tenant_avatar_upload_path, blank=True, null=True
    )
    first_name = models.CharField(max_length=64)
    last_name = models.CharField(max_length=64)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    rent_amount = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    deposit = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    tenancy_start_date = models.DateField(blank=True, null=True)
    tenancy_end_date = models.DateField(blank=True, null=True)
    employment_details = models.TextField(blank=True, null=True)
    guarantor_name = models.CharField(max_length=128, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    # FK
    property = models.ForeignKey(
        Property, blank=True, on_delete=models.CASCADE, related_name="property_tenants"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="organisation_tenants"
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class ComplianceAndCertification(CreatedAtUpdatedAtBaseModel):
    certificate_type = models.CharField(
        max_length=50,
        choices=CertificateType.choices,
        default=CertificateType.GAS_SAFETY_CERTIFICATE,
    )
    issue_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    certificate_number = models.PositiveIntegerField(blank=True, null=True)
    issued_by = models.CharField(max_length=255, blank=True, null=True)
    certificate_file = models.FileField(
        upload_to=certificate_file_upload_path, blank=True, null=True
    )

    # FK
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="compliance_certificates"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="organisation_certificates"
    )

    class Meta:
        verbose_name = "Compliance and Certification"
        verbose_name_plural = "Compliance and Certifications"

    def __str__(self):
        return f"Compliance Record {self.pk}"


class UploadDocument(CreatedAtUpdatedAtBaseModel):
    document_category = models.CharField(
        max_length=50,
        choices=DocumentCategoryType.choices,
        blank=True,
        null=True,
    )
    document_name = models.CharField(max_length=100, blank=True, null=True)
    tags = models.TextField(blank=True, null=True)
    files = models.ManyToManyField(
        DocumentFile, blank=True, related_name="upload_documents"
    )

    # fk
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="upload_documents"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="upload_documents"
    )

    def __str__(self):
        return f"Upload Document - {self.document_name}"


class Finance(CreatedAtUpdatedAtBaseModel):
    type = models.CharField(
        max_length=20, choices=TransactionType.choices, default=TransactionType.INCOME
    )
    category = models.CharField(
        max_length=20, choices=Category.choices, null=True, blank=True
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    date = models.DateField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    receipt = models.ManyToManyField(
        DocumentFile, blank=True, related_name="finance_documents"
    )
    # fk
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="finance_property"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="finance_organisation"
    )

    def __str__(self):
        return f"Finance - {self.type}"
