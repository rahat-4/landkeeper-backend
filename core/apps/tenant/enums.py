from django.db import models
from django.utils.translation import gettext_lazy as _


class PaymentProviderChoices(models.TextChoices):
    GOCARDLESS = "GOCARDLESS", _("GoCardless")
    STRIPE = "STRIPE", _("Stripe")


class PaymentMethodTypeChoices(models.TextChoices):
    DIRECT_DEBIT = "DIRECT_DEBIT", _("Direct Debit")
    CARD = "CARD", _("Card")


class PaymentMethodStatusChoices(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    ACTIVE = "ACTIVE", _("Active")
    FAILED = "FAILED", _("Failed")
    CANCELLED = "CANCELLED", _("Cancelled")


class RentPaymentStatusChoices(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    PROCESSING = "PROCESSING", _("Processing")
    CLEARED = "CLEARED", _("Cleared")
    FAILED = "FAILED", _("Failed")
    OVERDUE = "OVERDUE", _("Overdue")
    REFUNDED = "REFUNDED", _("Refunded")


class MaintenanceStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", _("Submitted")
    ASSIGNED = "ASSIGNED", _("Assigned")
    IN_PROGRESS = "IN_PROGRESS", _("In Progress")
    COMPLETED = "COMPLETED", _("Completed")


class MaintenanceCategory(models.TextChoices):
    PLUMBING_WATER = "PLUMBING_WATER", _("Plumbing & Water")
    HEATING_HOT_WATER = "HEATING_HOT_WATER", _("Heating & Hot Water")
    ELECTRICAL = "ELECTRICAL", _("Electrical")
    GAS = "GAS", _("Gas")
    ROOF_GUTTERING = "ROOF_GUTTERING", _("Roof & Guttering")
    DAMP_MOULD_CONDENSATION = "DAMP_MOULD_CONDENSATION", _("Damp, Mould & Condensation")
    DOORS_WINDOWS_LOCKS = "DOORS_WINDOWS_LOCKS", _("Doors, Windows & Locks")
    BATHROOM = "BATHROOM", _("Bathroom")
    KITCHEN = "KITCHEN", _("Kitchen")
    APPLIANCES = "APPLIANCES", _("Appliances")
    HEATING_VENTILATION = "HEATING_VENTILATION", _("Heating & Ventilation")
    STRUCTURAL_BUILDING = "STRUCTURAL_BUILDING", _("Structural & Building")
    PEST_CONTROL = "PEST_CONTROL", _("Pest Control")
    SECURITY_SAFETY = "SECURITY_SAFETY", _("Security & Safety")
    EXTERNAL_AREAS = "EXTERNAL_AREAS", _("External Areas")
    COMMUNAL_AREAS = "COMMUNAL_AREAS", _("Communal Areas")
    CLEANING_GENERAL = "CLEANING_GENERAL", _("Cleaning & General")
    OTHER_GENERAL_MAINTENANCE = "OTHER_GENERAL_MAINTENANCE", _(
        "Other / General Maintenance"
    )
