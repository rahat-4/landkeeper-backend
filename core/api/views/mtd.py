from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.mtd.models import MTD_FIRST_TAX_YEAR, MTDFinanceCost, MTDReport
from apps.mtd.services import (
    build_summary_pdf,
    calculate_report_summary,
    get_expense_entries,
    get_income_entries,
)
from apps.organisation.utils import get_request_organisation
from apps.property.models import Property, Mortgage
from common.permission import IsAdmin, IsLandlord, IsSuperAdmin

from ..serializers.mtd import (
    MTDIncomeExpenseSerializer,
    MTDFinanceCostSerializer,
    MTDPropertySelectionSerializer,
    MTDReportDeclarationSerializer,
    MTDReportPeriodSerializer,
    MTDReportSerializer,
)

MTD_PERMISSIONS = [IsSuperAdmin | IsLandlord | IsAdmin]


class MTDReportView(APIView):
    permission_classes = MTD_PERMISSIONS

    def get(self, request, *args, **kwargs):
        serializer = MTDReportPeriodSerializer(
            data=request.query_params,
        )
        serializer.is_valid(raise_exception=True)
        filters = serializer.validated_data

        # Both query parameters are mandatory.
        required_fields = ["tax_year", "quarter"]
        missing_fields = [field for field in required_fields if field not in filters]

        if missing_fields:
            return Response(
                {
                    "detail": (
                        "Both tax_year and quarter query parameters are required."
                    ),
                    "missing_fields": missing_fields,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        organisation = get_request_organisation(request)

        self.get_or_create_report(organisation, filters)

        reports = (
            MTDReport.objects.filter(
                organisation=organisation,
                **filters,
            )
            .prefetch_related("properties")
            .order_by("-tax_year", "-quarter")
        )

        return Response(
            MTDReportSerializer(
                reports,
                many=True,
                context={"include_summary": True},
            ).data
        )

    def get_or_create_report(self, organisation, period):
        try:
            with transaction.atomic():
                MTDReport.objects.get_or_create(
                    organisation=organisation,
                    **period,
                )
        except IntegrityError:
            # Another concurrent request may have created it first.
            pass


class MTDReportMixin:
    """Resolves the report from `report_alias` for nested MTD views."""

    permission_classes = MTD_PERMISSIONS

    def get_report(self):
        organisation = get_request_organisation(self.request)
        return get_object_or_404(
            MTDReport, alias=self.kwargs["report_alias"], organisation=organisation
        )


class MTDReportSummaryView(MTDReportMixin, APIView):
    """Properties table, totals for the ticked properties and the Summary tab."""

    def get(self, request, *args, **kwargs):
        report = self.get_report()
        return Response(
            {
                **calculate_report_summary(report),
            }
        )


class MTDPropertySelectionView(MTDReportMixin, APIView):
    """Set the ticked properties for the report and return the updated summary."""

    def put(self, request, *args, **kwargs):
        report = self.get_report()
        serializer = MTDPropertySelectionSerializer(
            data=request.data, context={"report": report}
        )
        serializer.is_valid(raise_exception=True)
        report.properties.set(serializer.validated_data["properties"])
        return Response(
            {
                "report": MTDReportSerializer(report).data,
                **calculate_report_summary(report),
            }
        )


class MTDIncomeExpensesView(MTDReportMixin, APIView):
    """Income and allowable expense entries for the ticked properties in the quarter."""

    def get(self, request, *args, **kwargs):
        report = self.get_report()
        return Response(
            {
                "income": MTDIncomeExpenseSerializer(
                    get_income_entries(report), many=True
                ).data,
                "expenses": MTDIncomeExpenseSerializer(
                    get_expense_entries(report), many=True
                ).data,
            }
        )


class MTDFinanceCostsView(MTDReportMixin, APIView):
    """
    GET:
        List mortgages for properties selected in the MTD report.

    PATCH:
        Update notes and evidence for a mortgage.
    """

    def get_mortgages(self, report):
        return (
            Mortgage.objects.filter(
                organisation_id=report.organisation_id,
                property__in=report.properties.all(),
            )
            .select_related("property")
            .prefetch_related(
                "mtd_finance_costs__evidence",
            )
            .order_by("property__property_name", "lender_name")
        )

    def get(self, request, *args, **kwargs):
        report = self.get_report()
        mortgages = self.get_mortgages(report)

        rows = []

        for mortgage in mortgages:
            finance_cost = mortgage.mtd_finance_costs.first()

            rows.append(
                {
                    "alias": str(mortgage.alias),
                    "property_name": mortgage.property.property_name,
                    "lender_name": mortgage.lender_name,
                    "monthly_payment": mortgage.monthly_payment,
                    "notes": finance_cost.notes if finance_cost else None,
                    "evidence": (
                        [
                            {
                                "id": str(document.pk),
                                "name": str(document),
                            }
                            for document in finance_cost.evidence.all()
                        ]
                        if finance_cost
                        else []
                    ),
                }
            )

        return Response({"finance_costs": rows})

    def patch(self, request, mortgage_alias, *args, **kwargs):
        report = self.get_report()

        # Only allow mortgages belonging to selected report properties
        mortgage = get_object_or_404(
            self.get_mortgages(report),
            alias=mortgage_alias,
        )

        finance_cost, _ = MTDFinanceCost.objects.get_or_create(
            mortgage=mortgage,
        )

        serializer = MTDFinanceCostSerializer(
            finance_cost,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            MTDFinanceCostSerializer(
                finance_cost,
                context={"request": request},
            ).data,
            status=status.HTTP_200_OK,
        )


class MTDReportDownloadView(MTDReportMixin, APIView):
    """Save the declaration and download the summary as a PDF."""

    def post(self, request, *args, **kwargs):
        report = self.get_report()
        serializer = MTDReportDeclarationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        for field, value in serializer.validated_data.items():
            setattr(report, field, value)
        report.updated_by = request.user
        report.save()

        buffer = build_summary_pdf(report, calculate_report_summary(report))
        filename = (
            f"MTD_Summary_{report.tax_year}-{str(report.tax_year + 1)[-2:]}"
            f"_{report.quarter}_-_Landkeeper.pdf"
        )
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
