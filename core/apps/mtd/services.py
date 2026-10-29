import io
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.property.enums import Category, TransactionType
from apps.property.models import Finance, Property, Mortgage

ZERO = Decimal("0.00")

INCOME_CATEGORIES = [Category.RENTAL_INCOME, Category.OTHER]
EXPENSE_CATEGORIES = [
    Category.MORTGAGE_PAYMENT,
    Category.REPAIRS,
    Category.INSURANCE,
    Category.SERVICE_CHARGES,
    Category.UTILITIES,
    Category.MANAGEMENT_FEES,
    Category.TAX,
    Category.OTHER,
]


def get_report_finance(report):
    """Finance entries for the report's properties dated within the period."""
    queryset = Finance.objects.filter(
        organisation_id=report.organisation_id,
        property__in=report.properties.all(),
    )

    return queryset


def get_income_entries(report):
    return (
        get_report_finance(report)
        .filter(type=TransactionType.INCOME, category__in=INCOME_CATEGORIES)
        .select_related("property")
        .order_by("date", "id")
    )


def get_expense_entries(report):
    return (
        get_report_finance(report)
        .filter(type=TransactionType.EXPENSE, category__in=EXPENSE_CATEGORIES)
        .select_related("property")
        .order_by("date", "id")
    )


def get_mortgage_interest(report):
    return Mortgage.objects.filter(
        organisation_id=report.organisation_id,
        property__in=report.properties.all(),
    ).select_related("property")


def calculate_report_summary(report):
    """Totals for the ticked properties, matching the Income & Expenses tab."""
    total_income = (
        get_income_entries(report).aggregate(total=Sum("amount"))["total"] or ZERO
    )
    total_allowable_expenses = (
        get_expense_entries(report).aggregate(total=Sum("amount"))["total"] or ZERO
    )
    total_mortgage_interest = (
        get_mortgage_interest(report).aggregate(total=Sum("monthly_payment"))["total"]
        or ZERO
    )
    total_properties = Property.objects.filter(organisation=report.organisation).count()

    return {
        "total_income": total_income,
        "total_allowable_expenses": total_allowable_expenses,
        "property_profit": total_income - total_allowable_expenses,
        "total_mortgage_interest": total_mortgage_interest,
        "total_properties": total_properties,
        "number_of_properties_included": report.properties.count(),
    }


def build_summary_pdf(report, summary):
    INK = colors.HexColor("#111827")
    SUBTLE = colors.HexColor("#6B7280")
    HAIRLINE = colors.HexColor("#E5E7EB")
    HIGHLIGHT = colors.HexColor("#EFF6FF")

    title_style = ParagraphStyle(
        "Title", fontName="Helvetica-Bold", fontSize=18, textColor=INK, leading=22
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", fontName="Helvetica", fontSize=9, textColor=SUBTLE, leading=12
    )
    heading_style = ParagraphStyle(
        "Heading",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=INK,
        spaceBefore=6,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "Body", fontName="Helvetica", fontSize=8.5, textColor=INK, leading=11
    )

    def fmt_money(value):
        return f"£{value:,.2f}"

    def fmt_date(value):
        return value.strftime("%d-%m-%Y") if value else ""

    def styled_table(rows, col_widths, highlight_rows=()):
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        style = [
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
            ("TEXTCOLOR", (0, 0), (-1, -1), INK),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, HAIRLINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        for row in highlight_rows:
            style += [
                ("BACKGROUND", (0, row), (-1, row), HIGHLIGHT),
                ("FONT", (0, row), (-1, row), "Helvetica-Bold", 8.5),
            ]
        table.setStyle(TableStyle(style))
        return table

    period = f"{fmt_date(report.period_start)} to {fmt_date(report.period_end)}"

    story = [
        Paragraph("Making Tax Digital (MTD) Summary", title_style),
        Paragraph(
            f"{escape(str(report.organisation))} &middot; Tax year {report.tax_year_label} &middot; "
            f"{report.get_quarter_display()} &middot; {period}",
            subtitle_style,
        ),
        Paragraph(
            f"Generated on {timezone.localtime().strftime('%d-%m-%Y %H:%M')}",
            subtitle_style,
        ),
        Spacer(1, 6 * mm),
        Paragraph("Summary", heading_style),
    ]

    summary_rows = [
        ["Category", "Amount (£)"],
        ["Total income", fmt_money(summary["total_income"])],
        [
            "Total allowable expenses",
            fmt_money(summary["total_allowable_expenses"]),
        ],
        ["PROPERTY PROFIT / (LOSS)", fmt_money(summary["property_profit"])],
        [
            "Number of properties included",
            str(summary["number_of_properties_included"]),
        ],
    ]
    story.append(styled_table(summary_rows, [120 * mm, 50 * mm], highlight_rows=(3,)))

    story += [Spacer(1, 6 * mm), Paragraph("Declaration", heading_style)]
    declarations = [
        (
            report.confirmed_all_properties_included,
            "I have included all relevant properties for this reporting period.",
        ),
        (
            report.confirmed_entries_checked,
            "I have checked the income and expense entries and identified estimates "
            "or missing evidence.",
        ),
        (
            report.confirmed_items_flagged,
            "I have flagged unusual items, capital improvements, private costs and "
            "finance costs for review.",
        ),
    ]
    for confirmed, text in declarations:
        mark = "[x]" if confirmed else "[ ]"
        story.append(Paragraph(f"{mark} {text}", body_style))
    story += [
        Spacer(1, 3 * mm),
        Paragraph(
            f"<b>Landlord / authorised person:</b> {escape(report.confirmed_by_name or '')}",
            body_style,
        ),
        Paragraph(f"<b>Date:</b> {fmt_date(report.confirmed_at)}", body_style),
    ]
    if report.review_notes:
        story.append(
            Paragraph(f"<b>Notes:</b> {escape(report.review_notes)}", body_style)
        )

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"MTD Summary {report.tax_year_label} {report.quarter}",
    ).build(story)
    buffer.seek(0)
    return buffer
