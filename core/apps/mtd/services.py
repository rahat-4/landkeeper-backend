import io
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.utils.html import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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


def get_rental_income(report):
    return (
        get_report_finance(report)
        .filter(type=TransactionType.INCOME, category=Category.RENTAL_INCOME)
        .select_related("property")
        .order_by("date", "id")
    )


def get_other_income(report):
    return (
        get_report_finance(report)
        .filter(type=TransactionType.INCOME, category=Category.OTHER)
        .select_related("property")
        .order_by("date", "id")
    )


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
    total_rental_income = (
        get_rental_income(report).aggregate(total=Sum("amount"))["total"] or ZERO
    )
    total_other_income = (
        get_other_income(report).aggregate(total=Sum("amount"))["total"] or ZERO
    )
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
        "total_rental_income": total_rental_income,
        "total_other_income": total_other_income,
        "total_income": total_income,
        "total_allowable_expenses": total_allowable_expenses,
        "property_profit": total_income - total_allowable_expenses,
        "total_mortgage_interest": total_mortgage_interest,
        "total_properties": total_properties,
        "number_of_properties_included": report.properties.count(),
    }


class Checkbox(Flowable):
    """Small drawn checkbox, ticked when `checked` is true."""

    def __init__(self, checked, size=3.6 * mm, color=colors.black):
        super().__init__()
        self.checked = checked
        self.size = size
        self.color = color
        self.width = self.height = size

    def draw(self):
        s = self.size
        c = self.canv
        if self.checked:
            c.setFillColor(self.color)
            c.setStrokeColor(self.color)
            c.roundRect(0, 0, s, s, 0.8, stroke=1, fill=1)
            c.setStrokeColor(colors.white)
            c.setLineWidth(1.2)
            c.setLineCap(1)
            c.setLineJoin(1)
            path = c.beginPath()
            path.moveTo(s * 0.22, s * 0.52)
            path.lineTo(s * 0.42, s * 0.30)
            path.lineTo(s * 0.78, s * 0.72)
            c.drawPath(path, stroke=1, fill=0)
        else:
            c.setStrokeColor(colors.HexColor("#9CA3AF"))
            c.setLineWidth(0.8)
            c.roundRect(0, 0, s, s, 0.8, stroke=1, fill=0)


def build_summary_pdf(report, summary):
    BRAND = colors.HexColor("#1E3A8A")
    INK = colors.HexColor("#111827")
    SUBTLE = colors.HexColor("#6B7280")
    HAIRLINE = colors.HexColor("#E5E7EB")
    PANEL = colors.HexColor("#F9FAFB")
    HIGHLIGHT = colors.HexColor("#EFF6FF")
    POSITIVE = colors.HexColor("#047857")
    NEGATIVE = colors.HexColor("#B91C1C")

    page_width, page_height = A4
    margin = 18 * mm
    content_width = page_width - 2 * margin

    title_style = ParagraphStyle(
        "Title", fontName="Helvetica-Bold", fontSize=20, textColor=INK, leading=24
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", fontName="Helvetica", fontSize=10, textColor=SUBTLE, leading=14
    )
    heading_style = ParagraphStyle(
        "Heading",
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=BRAND,
        leading=15,
        spaceAfter=3 * mm,
    )
    body_style = ParagraphStyle(
        "Body", fontName="Helvetica", fontSize=9.5, textColor=INK, leading=13
    )
    cell_style = ParagraphStyle("Cell", parent=body_style, fontSize=9.5, leading=12)
    cell_bold_style = ParagraphStyle(
        "CellBold", parent=cell_style, fontName="Helvetica-Bold"
    )
    label_style = ParagraphStyle(
        "Label", fontName="Helvetica", fontSize=7.5, textColor=SUBTLE, leading=10
    )
    value_style = ParagraphStyle(
        "Value", fontName="Helvetica-Bold", fontSize=10.5, textColor=INK, leading=13
    )

    def fmt_money(value):
        if value < 0:
            return f"(£{-value:,.2f})"
        return f"£{value:,.2f}"

    def fmt_date(value):
        return value.strftime("%d-%m-%Y") if value else ""

    def section(title):
        return [Spacer(1, 7 * mm), Paragraph(title, heading_style)]

    period = f"{fmt_date(report.period_start)} to {fmt_date(report.period_end)}"
    generated_at = timezone.localtime().strftime("%d-%m-%Y %H:%M")

    def draw_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, page_height - 6 * mm, page_width, 6 * mm, stroke=0, fill=1)
        canvas.setStrokeColor(HAIRLINE)
        canvas.setLineWidth(0.5)
        canvas.line(margin, 13 * mm, page_width - margin, 13 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(SUBTLE)
        canvas.drawString(
            margin, 9 * mm, f"Landkeeper  ·  MTD Summary  ·  Generated {generated_at}"
        )
        canvas.drawRightString(page_width - margin, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    # Header
    story = [
        Paragraph("Making Tax Digital Summary", title_style),
        Spacer(1, 1.5 * mm),
        Spacer(1, 6 * mm),
    ]

    # Key facts
    facts = [
        ("TAX YEAR", report.tax_year_label),
        ("QUARTER", report.get_quarter_display()),
        ("PERIOD", period),
        ("PROPERTIES", str(summary["number_of_properties_included"])),
    ]
    fact_cells = [
        [Paragraph(label, label_style), Paragraph(escape(str(value)), value_style)]
        for label, value in facts
    ]
    facts_table = Table(
        [fact_cells],
        colWidths=[
            content_width * 0.18,
            content_width * 0.22,
            content_width * 0.40,
            content_width * 0.20,
        ],
    )
    facts_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                ("BOX", (0, 0), (-1, -1), 0.5, HAIRLINE),
                ("LINEAFTER", (0, 0), (-2, -1), 0.5, HAIRLINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ]
        )
    )
    story.append(facts_table)

    # Summary
    story += section("Summary")
    profit = summary["property_profit"]
    summary_rows = [
        ("Total rental income", summary["total_rental_income"], "normal"),
        ("Total other property income", summary["total_other_income"], "normal"),
        ("Total property income", summary["total_income"], "total"),
        (
            "Total allowable property expenses",
            summary["total_allowable_expenses"],
            "normal",
        ),
        (
            "Net property profit / (loss) before finance-cost tax treatment",
            profit,
            "result",
        ),
        (
            "Total residential finance costs (separately recorded)",
            summary["total_mortgage_interest"],
            "normal",
        ),
    ]

    header_style = ParagraphStyle(
        "Header", parent=cell_bold_style, textColor=colors.white
    )
    header_right_style = ParagraphStyle(
        "HeaderRight", parent=header_style, alignment=TA_RIGHT
    )
    rows = [
        [Paragraph("Category", header_style), Paragraph("Amount", header_right_style)]
    ]
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, HAIRLINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6 * mm),
    ]
    for index, (label, amount, kind) in enumerate(summary_rows, start=1):
        label_para_style = cell_style if kind == "normal" else cell_bold_style
        amount_color = INK
        if kind == "result":
            amount_color = NEGATIVE if amount < 0 else POSITIVE
        amount_style = ParagraphStyle(
            f"Amount{index}",
            parent=label_para_style,
            alignment=TA_RIGHT,
            textColor=amount_color,
        )
        rows.append(
            [
                Paragraph(escape(label), label_para_style),
                Paragraph(fmt_money(amount), amount_style),
            ]
        )
        if kind != "normal":
            table_style.append(("BACKGROUND", (0, index), (-1, index), HIGHLIGHT))
        if kind == "result":
            table_style.append(("LINEABOVE", (0, index), (-1, index), 1, BRAND))

    summary_table = Table(
        rows, colWidths=[content_width * 0.72, content_width * 0.28], repeatRows=1
    )
    summary_table.setStyle(TableStyle(table_style))
    story.append(summary_table)

    # Declaration
    story += section("Declaration")
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
    declaration_table = Table(
        [
            [Checkbox(confirmed, color=BRAND), Paragraph(text, body_style)]
            for confirmed, text in declarations
        ],
        colWidths=[10 * mm, content_width - 10 * mm],
    )
    declaration_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 4 * mm),
                ("LEFTPADDING", (1, 0), (1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, HAIRLINE),
                ("BOX", (0, 0), (-1, -1), 0.5, HAIRLINE),
            ]
        )
    )
    story.append(declaration_table)

    # Sign-off
    story.append(Spacer(1, 5 * mm))
    signoff_rows = [
        [
            [
                Paragraph("LANDLORD / AUTHORISED PERSON", label_style),
                Paragraph(escape(report.confirmed_by_name or "—"), value_style),
            ],
            [
                Paragraph("DATE", label_style),
                Paragraph(fmt_date(report.confirmed_at) or "—", value_style),
            ],
        ]
    ]
    signoff_style = [
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, HAIRLINE),
        ("LINEAFTER", (0, 0), (0, 0), 0.5, HAIRLINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]
    if report.review_notes:
        notes = escape(report.review_notes).replace("\n", "<br/>")
        signoff_rows.append(
            [[Paragraph("NOTES", label_style), Paragraph(notes, body_style)], ""]
        )
        signoff_style += [
            ("SPAN", (0, 1), (1, 1)),
            ("LINEABOVE", (0, 1), (-1, 1), 0.5, HAIRLINE),
        ]
    signoff_table = Table(
        signoff_rows, colWidths=[content_width * 0.65, content_width * 0.35]
    )
    signoff_table.setStyle(TableStyle(signoff_style))
    story.append(KeepTogether([signoff_table]))

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=f"MTD Summary {report.tax_year_label} {report.quarter}",
        author="Landkeeper",
    ).build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    buffer.seek(0)
    return buffer
