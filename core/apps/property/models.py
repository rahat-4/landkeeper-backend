from django.db import models
from common.models import (
    CreatedAtUpdatedAtBaseModel,
    Media,
    DocumentFile
)
from .enums import (
    PropertyType,
    CertificateType,
    StatusType,
    PropertyProductType,
    MortgageProductType,
    DocumentCategoryType
)

class Property(CreatedAtUpdatedAtBaseModel):
    property_name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    property_type = models.CharField(
        max_length=20,
        choices=PropertyType.choices,
        default=PropertyType.RESIDENTIAL,
    )
    status = models.CharField(
        max_length=50,
        choices=StatusType.choices,
        blank=True,
        null=True,
    )
    purchase_date = models.DateField(blank=True, null=True)
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    current_valuation = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    product_type = models.CharField(
        max_length=50,
        choices=PropertyProductType.choices,
        blank=True,
        null=True,
    )
    bedrooms = models.PositiveIntegerField(blank=True, null=True)
    bathrooms = models.PositiveIntegerField(blank=True, null=True)
    ownership_type = models.CharField(max_length=50, blank=True, null=True)
    ownership_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
    )
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    images = models.ManyToManyField(Media, blank=True, related_name="property_images")
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.property_name

    @property
    def current_mortgage(self):
        return self.mortgages.filter(end_date__isnull=True).order_by("-start_date").first()


class Mortgage(CreatedAtUpdatedAtBaseModel):
    lender_name = models.CharField(max_length=255)
    mortgage_account_number = models.CharField(max_length=255, blank=True, null=True)
    mortgage_adviser = models.CharField(max_length=255, blank=True, null=True)
    mortgage_product_type = models.CharField(
        max_length=50,
        choices=MortgageProductType.choices,
        blank=True,
        null=True,
    )
    interest_rate = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    loan_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    monthly_payment = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    outstanding_balance = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    term = models.PositiveIntegerField(blank=True, null=True)
    early_repayment_charge = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    renewal_date = models.DateField(blank=True, null=True)
    broker_notes = models.TextField(blank=True, null=True)
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="mortgages"
    )

    def __str__(self):
        return f"{self.lender_name} - {self.mortgage_account_number}"


class Tenant(CreatedAtUpdatedAtBaseModel):
    tenant_name = models.CharField(max_length=255, blank=True, null=True)
    contact_details = models.TextField(blank=True, null=True)
    tenancy_start_date = models.DateField(blank=True, null=True)
    tenancy_end_date = models.DateField(blank=True, null=True)
    rent_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    deposit_amount = models.DecimalField(max_digits=20, decimal_places=2, blank=True, null=True)
    guarantor_details = models.TextField(blank=True, null=True)
    employment_details = models.TextField(blank=True, null=True)
    id_verification_records = models.TextField(blank=True, null=True)
    properties = models.ManyToManyField(
        Property,
        blank=True,
        related_name="tenants"
    )

    def __str__(self):
        return f"{self.tenant_name}"

class TenantDocument(CreatedAtUpdatedAtBaseModel):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="documents"
    )
    file = models.FileField(upload_to='tenant_documents/')
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.tenant.tenant_name}"

class ComplianceAndCertification(CreatedAtUpdatedAtBaseModel):
    certificate_type = models.CharField(
        max_length=50,
        choices=CertificateType.choices,
        blank=True,
        null=True,
    )
    issue_date = models.DateField(blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    certificate_number = models.PositiveIntegerField(blank=True, null=True)
    issued_by = models.CharField(max_length=255, blank=True, null=True)
    certificate_file = models.FileField(upload_to="compliance_certificates/", blank=True, null=True)
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="compliance_certificates"
    )

    class Meta:
        verbose_name = "Compliance and Certification"
        verbose_name_plural = "Compliance and Certifications"

    def __str__(self):
        return f"Compliance Record {self.pk}"

class UploadDocument(CreatedAtUpdatedAtBaseModel):
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="upload_documents"
    )
    document_category = models.CharField(
        max_length=50,
        choices=DocumentCategoryType.choices,
        blank=True,
        null=True,
    )
    document_name = models.CharField(max_length=100, blank=True, null=True)
    tags = models.TextField(blank=True, null=True)
    files = models.ManyToManyField(
        DocumentFile,
        blank=True,
        related_name="upload_documents",
    )

    def __str__(self):
        return f"Upload Document - {self.document_name}"