from django.db import models
from common.models import CreatedAtUpdatedAtBaseModel, Media
from .enums import PropertyType


class Property(CreatedAtUpdatedAtBaseModel):
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    property_type = models.CharField(
        max_length=20,
        choices=PropertyType.choices,
        default=PropertyType.RESIDENTIAL,
    )
    purchase_date = models.DateField(blank=True, null=True)
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    current_valuation = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    ownership_type = models.CharField(max_length=50, blank=True, null=True)
    ownership_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    images = models.ManyToManyField(Media, blank=True, related_name="property_images")
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class Mortgage(CreatedAtUpdatedAtBaseModel):
    lender_name = models.CharField(max_length=255)
    mortgage_account_number = models.CharField(max_length=255, blank=True, null=True)
    mortgage_adviser = models.CharField(max_length=255, blank=True, null=True)
    interest_rate = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True
    )
    variable_type = models.CharField(max_length=50, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    monthly_payment = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    outstanding_balance = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    early_repayment_charge = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True
    )
    renewal_date = models.DateField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="mortgages"
    )

    def __str__(self):
        return f"{self.lender_name} - {self.mortgage_account_number}"
