from django.urls import path
from api.views.report import (
    PropertyPortfolioExportView,
    IncomeReportView,
    ExpenseReportView,
)

urlpatterns = [
    path(
        "/properties-portfolio",
        PropertyPortfolioExportView.as_view(),
        name="properties-portfolio",
    ),
    path("/income", IncomeReportView.as_view(), name="income"),
    path("/expense", ExpenseReportView.as_view(), name="expense"),
]
