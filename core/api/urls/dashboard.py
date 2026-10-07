from django.urls import path

from ..views.dashboard import (
    DashboardSummaryView,
    PropertyTypeDashboardView,
    ComplianceTypeDashboardView,
    DashboardIncomeExpenseDashboardView,
    AlertsDashboardAPIView,
)

urlpatterns = [
    path(
        "/summary",
        DashboardSummaryView.as_view(),
        name="dashboard-summary",
    ),
    path(
        "/property-types",
        PropertyTypeDashboardView.as_view(),
        name="dashboard-property-types",
    ),
    path(
        "/compliance-types",
        ComplianceTypeDashboardView.as_view(),
        name="dashboard-compliance-types",
    ),
    path(
        "/income-expense",
        DashboardIncomeExpenseDashboardView.as_view(),
        name="dashboard-income-expense",
    ),
    path(
        "/alerts",
        AlertsDashboardAPIView.as_view(),
        name="dashboard-alerts"
    ),
]
