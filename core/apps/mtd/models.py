from datetime import date

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.organisation.models import Organisation
from apps.property.models import Property, Mortgage
from common.models import CreatedAtUpdatedAtBaseModel, DocumentFile

from .enums import MTDQuarter

# MTD reports are available from the 2025/26 tax year onwards.
MTD_FIRST_TAX_YEAR = 2025

# (start month, start day, end month, end day, end-year offset from tax year start)
QUARTER_DATES = {
    MTDQuarter.Q1: (4, 6, 7, 5, 0),
    MTDQuarter.Q2: (7, 6, 10, 5, 0),
    MTDQuarter.Q3: (10, 6, 1, 5, 1),
    MTDQuarter.Q4: (1, 6, 4, 5, 1),
}


def get_quarter_dates(tax_year, quarter):
    start_month, start_day, end_month, end_day, end_offset = QUARTER_DATES[quarter]
    start_offset = 1 if quarter == MTDQuarter.Q4 else 0
    return (
        date(tax_year + start_offset, start_month, start_day),
        date(tax_year + end_offset, end_month, end_day),
    )


def get_period_for_date(day):
    """Return (tax_year, quarter) that `day` falls in."""
    tax_year = day.year if day >= date(day.year, 4, 6) else day.year - 1
    for quarter in MTDQuarter.values:
        start, end = get_quarter_dates(tax_year, quarter)
        if start <= day <= end:
            return tax_year, quarter


class MTDReport(CreatedAtUpdatedAtBaseModel):
    # Start year of the tax year, e.g. 2026 for 2026/27
    tax_year = models.PositiveIntegerField(
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
        verbose_name=_("Tax Year"),
    )
    quarter = models.CharField(
        max_length=2,
        choices=MTDQuarter.choices,
        verbose_name=_("Quarter"),
    )

    # Properties ticked for this report; totals and entries only cover these.
    properties = models.ManyToManyField(
        Property, blank=True, related_name="mtd_reports"
    )

    # Declaration completed before downloading the summary
    confirmed_all_properties_included = models.BooleanField(default=False)
    confirmed_entries_checked = models.BooleanField(default=False)
    confirmed_items_flagged = models.BooleanField(default=False)
    confirmed_by_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Landlord / Authorised Person"),
    )
    confirmed_at = models.DateField(blank=True, null=True)
    review_notes = models.TextField(blank=True, null=True)

    # Fk
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name="mtd_reports"
    )

    class Meta:
        verbose_name = _("MTD Report")
        verbose_name_plural = _("MTD Reports")
        ordering = ["-tax_year", "-quarter"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "tax_year", "quarter"],
                name="unique_mtd_report_per_org_quarter",
            )
        ]

    @property
    def period_start(self):
        return get_quarter_dates(self.tax_year, self.quarter)[0]

    @property
    def period_end(self):
        return get_quarter_dates(self.tax_year, self.quarter)[1]

    @property
    def tax_year_label(self):
        return f"{self.tax_year}/{str(self.tax_year + 1)[-2:]}"

    @property
    def is_declared(self):
        return bool(
            self.confirmed_all_properties_included
            and self.confirmed_entries_checked
            and self.confirmed_items_flagged
            and self.confirmed_by_name
        )

    def __str__(self):
        return f"MTD {self.tax_year_label} {self.quarter} - {self.organisation}"


class MTDFinanceCost(CreatedAtUpdatedAtBaseModel):
    mortgage = models.ForeignKey(
        Mortgage, on_delete=models.CASCADE, related_name="mtd_finance_costs"
    )
    notes = models.TextField(blank=True, null=True)
    evidence = models.ManyToManyField(
        DocumentFile, blank=True, related_name="mtd_finance_evidence"
    )

    def __str__(self):
        return f"MTD Finance Cost for {self.mortgage.lender_name} - {self.created_at}"
