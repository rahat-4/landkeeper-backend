from django.urls import path

from ..views.mtd import (
    MTDFinanceCostsView,
    MTDIncomeExpensesView,
    MTDPropertySelectionView,
    MTDReportDownloadView,
    MTDReportView,
    MTDReportSummaryView,
)

urlpatterns = [
    path("/reports", MTDReportView.as_view(), name="mtd-reports"),
    path(
        "/reports/<uuid:report_alias>/properties",
        MTDPropertySelectionView.as_view(),
        name="mtd-report-properties",
    ),
    path(
        "/reports/<uuid:report_alias>/income-expenses",
        MTDIncomeExpensesView.as_view(),
        name="mtd-report-income-expenses",
    ),
    path(
        "/reports/<uuid:report_alias>/finance-costs",
        MTDFinanceCostsView.as_view(),
        name="mtd-finance-costs",
    ),
    path(
        "/reports/<uuid:report_alias>/finance-costs/<uuid:mortgage_alias>",
        MTDFinanceCostsView.as_view(),
        name="mtd-finance-cost-detail",
    ),
    path(
        "/reports/<uuid:report_alias>/summary",
        MTDReportSummaryView.as_view(),
        name="mtd-report-summary",
    ),
    path(
        "/reports/<uuid:report_alias>/download",
        MTDReportDownloadView.as_view(),
        name="mtd-report-download",
    ),
]
