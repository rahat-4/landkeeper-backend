from django.contrib.auth.models import AbstractBaseUser
from django.db import models
from apps.organisation.models import Organisation
from apps.authentication.enums import NameTitleChoices
from common.models import CreatedAtUpdatedAtBaseModel, Media, DocumentFile
from django.conf import settings
from django.contrib.auth import get_user_model
from .enums import (
    PropertyType,
    CertificateType,
    StatusType,
    ProductType,
    DocumentCategoryType,
    TransactionType,
    Category,
    PropertyOwnerType,
    PropertyTenureType,
)
from .managers import ApplicantManager
from .utils import certificate_file_upload_path, tenant_avatar_upload_path

User = get_user_model()


class Property(CreatedAtUpdatedAtBaseModel):
    property_name = models.CharField(max_length=255)
    property_owner = models.CharField(
        max_length=64,
        choices=PropertyOwnerType.choices,
        default=PropertyOwnerType.OWNER,
    )
    company_name = models.CharField(max_length=64, null=True, blank=True)
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
    year_built = models.PositiveIntegerField(blank=True, null=True)
    property_tenure = models.CharField(
        max_length=64, choices=PropertyTenureType.choices, null=True, blank=True
    )
    remaining_lease_term = models.PositiveIntegerField(blank=True, null=True)
    monthly_service_charge = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    annual_ground_rent = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    bedrooms = models.PositiveIntegerField(blank=True, null=True)
    bathrooms = models.PositiveIntegerField(blank=True, null=True)
    monthly_rental_income = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    council_tax_band = models.CharField(max_length=64, null=True, blank=True)
    local_authority = models.CharField(max_length=64, null=True, blank=True)
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


class PropertyOwnership(CreatedAtUpdatedAtBaseModel):
    property = models.ForeignKey(
        Property,
        on_delete=models.CASCADE,
        related_name="shareholder",
    )
    owner_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    shareholder_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )
    share_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.owner_name} ({self.share_percentage}%)"


class Mortgage(CreatedAtUpdatedAtBaseModel):
    lender_name = models.CharField(max_length=255)
    interest_rate_type = models.CharField(
        max_length=50, choices=ProductType.choices, null=True, blank=True
    )
    interest_rate = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    interest_rate_expiry_date = models.DateField(blank=True, null=True)
    outstanding_balance = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    monthly_payment = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    remaining_mortgage = models.PositiveIntegerField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    epc_rating = models.CharField(max_length=10, blank=True, null=True)
    epc_certificate_expiry_date = models.DateField(blank=True, null=True)
    mortgage_documents = models.ManyToManyField(
        DocumentFile, blank=True, related_name="mortgages"
    )

    # FK
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="property_mortgages"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="organisation_mortgages"
    )

    def __str__(self):
        return f"{self.lender_name}"


class Tenant(AbstractBaseUser, CreatedAtUpdatedAtBaseModel):
    avatar = models.ImageField(
        upload_to=tenant_avatar_upload_path, blank=True, null=True
    )
    title = models.CharField(
        max_length=20,
        choices=NameTitleChoices.choices,
        blank=True,
        null=True,
    )
    first_name = models.CharField(max_length=64)
    middle_name = models.CharField(max_length=64, blank=True, null=True)
    last_name = models.CharField(max_length=64)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    image = models.ImageField(upload_to="tenants/", blank=True, null=True)
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
    is_active = models.BooleanField(default=False)
    is_password_set = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)
    is_staff = False
    is_superuser = False

    # FK
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="property_tenants"
    )
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="organisation_tenants"
    )

    USERNAME_FIELD = "email"

    objects = ApplicantManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "email"],
                name="unique_tenant_email_per_org",
            )
        ]
        indexes = [
            models.Index(fields=["organisation", "email"]),
        ]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower().strip()

        if self.property_id:
            self.organisation_id = self.property.organisation_id

        super().save(*args, **kwargs)

    def get_full_name(self):
        parts = [self.title, self.first_name, self.middle_name, self.last_name]
        full_name = " ".join(filter(None, parts))
        return full_name.strip().title()

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
    certificate_number = models.CharField(max_length=255, blank=True, null=True)
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


class ComplianceShare(CreatedAtUpdatedAtBaseModel):
    compliance = models.ForeignKey(
        ComplianceAndCertification,
        on_delete=models.CASCADE,
        related_name="shares"
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="compliance_shares"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["compliance", "tenant"],
                name="unique_compliance_tenant_share",
            )
        ]

    def __str__(self):
        return f"Compliance Record {self.compliance_id} Share with {self.tenant_id}"


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
    other_category = models.CharField(max_length=100, blank=True, null=True)
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
