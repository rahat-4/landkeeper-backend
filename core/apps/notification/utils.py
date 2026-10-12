from io import BytesIO

from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape
from django.conf import settings
from django.core.mail import EmailMessage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from apps.property.models import ComplianceAndCertification
from apps.supportticket.models import SupportTicket
from apps.tenant.models import MaintenanceRequest, MaintenanceRequestComment


def enrich_notification_data(data):
    data = dict(data)

    if data.get("type") == "SUPPORT_TICKET":
        ticket = SupportTicket.objects.filter(alias=data.get("alias")).first()
        data["is_deleted"] = ticket.is_deleted if ticket else True

    elif data.get("type") == "MAINTENANCE_REQUEST":
        if data.get("comment_id"):
            comment = MaintenanceRequestComment.objects.filter(
                pk=data["comment_id"]
            ).first()
            data["is_deleted"] = comment is None
        else:
            maintenance_request = MaintenanceRequest.objects.filter(
                alias=data.get("alias")
            ).first()
            data["is_deleted"] = maintenance_request is None
        data.pop("category", None)

    elif data.get("type") == "COMPLIANCE_CERTIFICATE":
        data["is_deleted"] = not ComplianceAndCertification.objects.filter(
            alias=data.get("alias")
        ).exists()

    data.pop("comment_id", None)

    return data


def _styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="EmergencyBanner",
            fontSize=11,
            textColor=colors.HexColor("#b91c1c"),
            fontName="Helvetica-Bold",
        )
    )
    return styles


def _build_maintenance_request_pdf(maintenance_request):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm
    )
    styles = _styles()
    elements = []

    if maintenance_request.is_emergency:
        elements.append(
            Paragraph("&#9888; EMERGENCY REQUEST", styles["EmergencyBanner"])
        )
        elements.append(Spacer(1, 10))

    elements.append(Paragraph("New Maintenance Request", styles["Title"]))
    elements.append(
        Paragraph(
            f"Submitted by {maintenance_request.tenant.get_full_name()}",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 16))

    data = [
        ["Property", str(maintenance_request.property)],
        ["Category", maintenance_request.get_category_display()],
        ["Issue", maintenance_request.issue or "N/A"],
        ["Description", maintenance_request.notes or "N/A"],
        ["Emergency", "Yes" if maintenance_request.is_emergency else "No"],
    ]

    table = Table(data, colWidths=[100, 320])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#6b7280")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def _build_maintenance_status_pdf(maintenance_request, status_display):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm
    )
    styles = _styles()
    elements = []

    elements.append(Paragraph("Maintenance Request Updated", styles["Title"]))
    elements.append(
        Paragraph(f"Status changed to: <b>{status_display}</b>", styles["Normal"])
    )
    elements.append(Spacer(1, 16))

    data = [
        ["Property", str(maintenance_request.property)],
        ["Category", maintenance_request.get_category_display()],
        ["Issue", maintenance_request.issue or "N/A"],
    ]

    table = Table(data, colWidths=[100, 320])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#6b7280")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def send_maintenance_request_created_email(maintenance_request, user):
    pdf_buffer = _build_maintenance_request_pdf(maintenance_request)

    body = (
        f"New maintenance request from {maintenance_request.tenant.get_full_name()} "
        f"for {maintenance_request.property}.\n\n"
        f"See the attached PDF for full details."
    )

    email = EmailMessage(
        subject="New Maintenance Request",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.attach(
        f"maintenance-request-{maintenance_request.alias}.pdf",
        pdf_buffer.read(),
        "application/pdf",
    )
    email.send(fail_silently=False)


def send_maintenance_status_changed_email(maintenance_request, tenant):
    status_display = maintenance_request.get_current_status_display()
    pdf_buffer = _build_maintenance_status_pdf(maintenance_request, status_display)

    body = f"Your maintenance request status has been changed to {status_display}.\n\nSee the attached PDF for full details."

    email = EmailMessage(
        subject="Maintenance Request Status Updated",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[tenant.email],
    )
    email.attach(
        f"maintenance-request-{maintenance_request.alias}.pdf",
        pdf_buffer.read(),
        "application/pdf",
    )
    email.send(fail_silently=False)


def send_certificate_expiry_email(certificate, user, days_left):
    certificate_name = certificate.get_certificate_type_display()

    body = (
        f"The {certificate_name} for {certificate.property} expires in "
        f"{days_left} days on {certificate.expiry_date:%d %b %Y}.\n\n"
        f"Certificate number: {certificate.certificate_number or 'N/A'}\n"
        f"Issued by: {certificate.issued_by or 'N/A'}\n\n"
        f"Please arrange a renewal before it expires to stay compliant."
    )

    if days_left <= 3:
        accent, accent_bg, label = "#C0392B", "#FDECEA", "Urgent"
    elif days_left <= 15:
        accent, accent_bg, label = "#B9770E", "#FEF5E7", "Action needed soon"
    else:
        accent, accent_bg, label = "#1F6FB2", "#EAF2FB", "Upcoming renewal"

    name = escape(certificate_name)
    prop = escape(str(certificate.property))
    number = escape(certificate.certificate_number or "N/A")
    issuer = escape(certificate.issued_by or "N/A")
    expiry = f"{certificate.expiry_date:%d %b %Y}"

    def row(label_text, value, last=False, colour="#1F2933"):
        border = "" if last else "border-bottom:1px solid #E4E7EB;"
        return f"""
        <tr>
          <td style="padding:12px 0;{border}color:#7B8794;font-size:14px;">{label_text}</td>
          <td align="right" style="padding:12px 0;{border}color:{colour};font-size:14px;font-weight:600;">{value}</td>
        </tr>"""

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F4F5F7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1F2933;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F4F5F7;">
    <tr><td align="center" style="padding:32px 16px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#FFFFFF;border-radius:12px;overflow:hidden;">

        <tr><td style="height:6px;background:{accent};font-size:0;line-height:0;">&nbsp;</td></tr>

        <tr><td style="padding:32px 32px 8px;">
          <span style="display:inline-block;padding:4px 12px;border-radius:999px;background:{accent_bg};color:{accent};font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.6px;">{label}</span>
          <h1 style="margin:16px 0 8px;font-size:22px;line-height:1.3;color:#1F2933;">{name} expires in {days_left} days</h1>
          <p style="margin:0;font-size:15px;line-height:1.6;color:#52606D;">The {name} for <strong style="color:#1F2933;">{prop}</strong> expires in {days_left} days on {expiry}.</p>
        </td></tr>

        <tr><td style="padding:24px 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{accent_bg};border-radius:10px;">
            <tr><td align="center" style="padding:20px;">
              <div style="font-size:44px;line-height:1;font-weight:800;color:{accent};">{days_left}</div>
              <div style="margin-top:6px;font-size:13px;font-weight:600;color:{accent};text-transform:uppercase;letter-spacing:0.8px;">days left &middot; expires {expiry}</div>
            </td></tr>
          </table>
        </td></tr>

        <tr><td style="padding:0 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            {row("Certificate number", number)}
            {row("Issued by", issuer)}
            {row("Expiry date", expiry, last=True, colour=accent)}
          </table>
        </td></tr>

        <tr><td style="padding:24px 32px 32px;">
          <p style="margin:0;padding:14px 16px;background:#F8F9FA;border-left:4px solid {accent};border-radius:4px;font-size:14px;line-height:1.6;color:#3E4C59;">
            Please arrange a renewal before it expires to stay compliant.
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    email = EmailMultiAlternatives(
        subject=f"{certificate_name} expires in {days_left} days",
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    email.attach_alternative(html_body, "text/html")
    email.send(fail_silently=False)