import logging
from django.utils import timezone
from asgiref.sync import async_to_sync
from datetime import timedelta
from apps.property.models import ComplianceAndCertification
from apps.notification.utils import send_certificate_expiry_email
from celery import shared_task
from channels.layers import get_channel_layer
from django.apps import apps
from apps.authentication.models import User
from apps.notification.enums import NotificationType
from apps.notification.models import Notification
from apps.notification.utils import (
    enrich_notification_data,
    send_maintenance_request_created_email,
    send_maintenance_status_changed_email,
)
from apps.organisation.enums import OrganisationRoleChoices
from apps.organisation.models import OrganisationUser
from apps.property.models import Tenant
from apps.tenant.models import MaintenanceRequest, MaintenanceRequestComment

logger = logging.getLogger(__name__)


def get_support_admins():
    return User.objects.filter(is_staff=True, is_active=True)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def create_notification_task(
    self,
    recipient_id,
    notification_type,
    message,
    data=None,
    actor_id=None,
):
    try:
        if recipient_id == actor_id:
            return None

        notification = Notification.objects.create(
            recipient_id=recipient_id,
            notification_type=notification_type,
            message=message,
            data=data or {},
            created_by_id=actor_id,
        )

        channel_layer = get_channel_layer()
        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                f"notifications_{recipient_id}",
                {
                    "type": "send_notification",
                    "payload": {
                        "id": notification.id,
                        "title": notification.get_notification_type_display(),
                        "description": notification.message,
                        "data": enrich_notification_data(notification.data),
                        "is_read": notification.is_read,
                        "read_at": (
                            notification.read_at.isoformat()
                            if notification.read_at
                            else None
                        ),
                        "created_at": notification.created_at.isoformat(),
                    },
                },
            )

        return str(notification.alias)
    except Exception as exc:
        logger.exception(
            "Failed to create notification for recipient_id=%s", recipient_id
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def push_tenant_notification_task(
    self,
    tenant_id,
    notification_type,
    message,
    data=None,
):
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.warning(
                "push_tenant_notification_task: no channel layer configured, "
                "skipping live push for tenant_id=%s",
                tenant_id,
            )
            return

        async_to_sync(channel_layer.group_send)(
            f"notifications_{tenant_id}",
            {
                "type": "send_notification",
                "payload": {
                    "title": notification_type,
                    "description": message,
                    "data": enrich_notification_data(data or {}),
                    "is_read": False,
                    "read_at": None,
                    "created_at": timezone.now().isoformat(),
                },
            },
        )
    except Exception as exc:
        logger.exception(
            "Failed to push live notification for tenant_id=%s",
            tenant_id,
        )
        raise self.retry(exc=exc)


@shared_task
def notify_ticket_created_task(ticket_id):
    SupportTicket = apps.get_model("supportticket", "SupportTicket")
    try:
        ticket = SupportTicket.objects.select_related("created_by").get(pk=ticket_id)
    except SupportTicket.DoesNotExist:
        logger.warning(
            "notify_ticket_created_task: ticket %s no longer exists", ticket_id
        )
        return

    for admin in get_support_admins():
        create_notification_task.delay(
            recipient_id=admin.id,
            notification_type=NotificationType.NEW_SUPPORT_TICKET,
            message=f"New support ticket: {ticket.ticket_id} – {ticket.subject or ''}".strip(
                " –"
            ),
            data={"type": "SUPPORT_TICKET", "alias": str(ticket.alias)},
            actor_id=ticket.created_by_id,
        )


@shared_task
def notify_ticket_status_updated_task(ticket_id, updated_by_id=None):
    SupportTicket = apps.get_model("supportticket", "SupportTicket")
    try:
        ticket = SupportTicket.objects.select_related("created_by").get(pk=ticket_id)
    except SupportTicket.DoesNotExist:
        logger.warning(
            "notify_ticket_status_updated_task: ticket %s no longer exists", ticket_id
        )
        return

    if not ticket.created_by_id:
        return

    create_notification_task.delay(
        recipient_id=ticket.created_by_id,
        notification_type=NotificationType.TICKET_STATUS_CHANGED,
        message=f"Ticket {ticket.ticket_id} status changed to {ticket.get_status_display()}",
        data={"type": "SUPPORT_TICKET", "alias": str(ticket.alias)},
        actor_id=updated_by_id or ticket.updated_by_id,
    )


@shared_task
def notify_new_comment_task(comment_id):
    SupportTicketComment = apps.get_model("supportticket", "SupportTicketComment")
    try:
        comment = SupportTicketComment.objects.select_related("ticket", "author").get(
            pk=comment_id
        )
    except SupportTicketComment.DoesNotExist:
        logger.warning(
            "notify_new_comment_task: comment %s no longer exists", comment_id
        )
        return

    ticket = comment.ticket
    recipient_ids = {
        ticket.created_by_id,
        *get_support_admins().values_list("id", flat=True),
    }
    recipient_ids.discard(comment.author_id)
    recipient_ids.discard(None)

    for recipient_id in recipient_ids:
        create_notification_task.delay(
            recipient_id=recipient_id,
            notification_type=NotificationType.NEW_TICKET_COMMENT,
            message=f"{comment.author.get_full_name()} commented on {ticket.ticket_id}: {comment.message[:150]}",
            data={"type": "SUPPORT_TICKET", "alias": str(ticket.alias)},
            actor_id=comment.author_id,
        )


@shared_task
def cleanup_old_notifications(days=30):
    from django.utils import timezone

    cutoff = timezone.now() - timezone.timedelta(days=days)
    deleted_count, _ = Notification.objects.filter(
        is_read=True, read_at__lt=cutoff
    ).delete()
    logger.info("cleanup_old_notifications: deleted %s notifications", deleted_count)
    return deleted_count


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def notify_maintenance_request_created_task(
    self,
    maintenance_request_id,
):
    try:
        maintenance_request = MaintenanceRequest.objects.select_related(
            "tenant",
            "property",
            "organisation",
        ).get(pk=maintenance_request_id)

        organisation = maintenance_request.organisation

        organisation_users = OrganisationUser.objects.filter(
            organisation=organisation,
            role__in=[
                OrganisationRoleChoices.LANDLORD,
                OrganisationRoleChoices.ADMIN,
                OrganisationRoleChoices.LETTING_AGENT,
            ],
            user__is_active=True,
        ).select_related("user")

        message = (
            f"New maintenance request from "
            f"{maintenance_request.tenant.get_full_name()} "
            f"for {maintenance_request.property}."
        )

        data = {
            "type": "MAINTENANCE_REQUEST",
            "alias": str(maintenance_request.alias),
            "category": maintenance_request.category,
            "is_emergency": maintenance_request.is_emergency,
        }

        for organisation_user in organisation_users:
            user = organisation_user.user

            # Database notification
            create_notification_task.delay(
                recipient_id=user.id,
                notification_type=NotificationType.NEW_MAINTENANCE_REQUEST,
                message=message,
                data=data,
                actor_id=None,
            )

            # Email notification
            send_maintenance_request_email.delay(
                maintenance_request.id,
                user.id,
            )

    except MaintenanceRequest.DoesNotExist:
        logger.warning(
            "Maintenance request %s no longer exists",
            maintenance_request_id,
        )
        return

    except Exception as exc:
        logger.exception(
            "Failed to notify organisation users for maintenance request %s",
            maintenance_request_id,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_maintenance_request_email(self, maintenance_request_id, user_id):
    try:
        maintenance_request = MaintenanceRequest.objects.select_related(
            "tenant", "property", "organisation"
        ).get(pk=maintenance_request_id)
        user = User.objects.get(pk=user_id, is_active=True)

        send_maintenance_request_created_email(maintenance_request, user)

    except Exception as exc:
        logger.exception(
            "Failed to send maintenance request email for request %s",
            maintenance_request_id,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def notify_maintenance_status_changed_task(
    self,
    maintenance_request_id,
    updated_by_id=None,
):
    try:
        maintenance_request = MaintenanceRequest.objects.select_related(
            "tenant",
            "property",
            "organisation",
        ).get(pk=maintenance_request_id)

        tenant = maintenance_request.tenant

        if not tenant:
            return

        message = (
            f"Your maintenance request for {maintenance_request.property} "
            f"is now {maintenance_request.get_current_status_display()}."
        )

        data = {
            "type": "MAINTENANCE_REQUEST",
            "alias": str(maintenance_request.alias),
            "category": maintenance_request.category,
            "is_emergency": maintenance_request.is_emergency,
        }

        # Database notification
        Notification.objects.create(
            tenant=tenant,
            notification_type=NotificationType.MAINTENANCE_STATUS_CHANGED,
            message=message,
            data=data,
        )

        # Push notification
        push_tenant_notification_task.delay(
            tenant_id=tenant.id,
            notification_type=NotificationType.MAINTENANCE_STATUS_CHANGED,
            message=message,
            data=data,
        )

        # Email notification
        send_maintenance_status_email.delay(
            maintenance_request.id,
            tenant.id,
        )

    except MaintenanceRequest.DoesNotExist:
        logger.warning(
            "Maintenance request %s no longer exists",
            maintenance_request_id,
        )

    except Exception as exc:
        logger.exception(
            "Failed to notify tenant about maintenance request %s",
            maintenance_request_id,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_maintenance_status_email(self, maintenance_request_id, tenant_id):
    try:
        maintenance_request = MaintenanceRequest.objects.select_related(
            "tenant", "property", "organisation"
        ).get(pk=maintenance_request_id)
        tenant = Tenant.objects.get(pk=tenant_id, is_active=True)

        send_maintenance_status_changed_email(maintenance_request, tenant)

    except Exception as exc:
        logger.exception(
            "Failed to send maintenance status email for request %s",
            maintenance_request_id,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def notify_maintenance_comment_created_task(self, comment_id):
    try:
        comment = MaintenanceRequestComment.objects.select_related(
            "staff_author",
            "tenant_author",
            "maintenance_request",
            "maintenance_request__tenant",
            "maintenance_request__property",
            "maintenance_request__organisation",
        ).get(pk=comment_id)

        maintenance_request = comment.maintenance_request
        organisation = maintenance_request.organisation

        data = {
            "type": "MAINTENANCE_REQUEST",
            "alias": str(maintenance_request.alias),
            "comment_id": comment.id,
            "is_deleted": False,
        }

        if comment.staff_author_id:
            tenant = maintenance_request.tenant

            if not tenant or not tenant.is_active:
                return

            message = (
                f"New comment from {maintenance_request.property} landlord "
                f"on your maintenance request."
            )

            Notification.objects.create(
                tenant=tenant,
                notification_type=NotificationType.NEW_MAINTENANCE_COMMENT,
                message=message,
                data=data,
            )

            push_tenant_notification_task.delay(
                tenant_id=tenant.id,
                notification_type=NotificationType.NEW_MAINTENANCE_COMMENT,
                message=message,
                data=data,
            )

        else:
            message = (
                f"New comment from {comment.tenant_author.get_full_name()} "
                f"on maintenance request for {maintenance_request.property}."
            )

            landlord_users = OrganisationUser.objects.filter(
                organisation=organisation,
                role=OrganisationRoleChoices.LANDLORD,
                user__is_active=True,
            ).select_related("user")

            for organisation_user in landlord_users:
                create_notification_task.delay(
                    recipient_id=organisation_user.user_id,
                    notification_type=NotificationType.NEW_MAINTENANCE_COMMENT,
                    message=message,
                    data=data,
                    actor_id=None,
                )

    except MaintenanceRequestComment.DoesNotExist:
        logger.warning(
            "Maintenance request comment %s no longer exists",
            comment_id,
        )
        return

    except Exception as exc:
        logger.exception(
            "Failed to notify about maintenance request comment %s",
            comment_id,
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def mark_comment_notifications_deleted_task(self, comment_id):
    try:
        notifications = Notification.objects.filter(data__comment_id=comment_id)

        for notification in notifications:
            notification.data = {**notification.data, "is_deleted": True}
            notification.save(update_fields=["data"])

    except Exception as exc:
        logger.exception(
            "Failed to mark notifications deleted for comment_id=%s", comment_id
        )
        raise self.retry(exc=exc)




CERTIFICATE_REMINDER_DAYS = [30, 15, 3]
@shared_task
def check_certificate_expiry_task():
    today = timezone.localdate()

    for days_left in CERTIFICATE_REMINDER_DAYS:
        target_date = today + timedelta(days=days_left)

        certificate_ids = ComplianceAndCertification.objects.filter(
            expiry_date=target_date,
            organisation__is_active=True,
        ).values_list("id", flat=True)

        for certificate_id in certificate_ids:
            notify_certificate_expiry_task.delay(certificate_id, days_left)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def notify_certificate_expiry_task(self, certificate_id, days_left):
    try:
        certificate = ComplianceAndCertification.objects.select_related(
            "property", "organisation"
        ).get(pk=certificate_id)

        landlord_users = OrganisationUser.objects.filter(
            organisation=certificate.organisation,
            role=OrganisationRoleChoices.LANDLORD,
            user__is_active=True,
        ).select_related("user")

        certificate_name = certificate.get_certificate_type_display()
        message = (
            f"{certificate_name} for {certificate.property} expires in "
            f"{days_left} days ({certificate.expiry_date:%d %b %Y})."
        )

        data = {
            "type": "COMPLIANCE_CERTIFICATE",
            "alias": str(certificate.alias),
            # "certificate_type": certificate.certificate_type,
            "expiry_date": certificate.expiry_date.isoformat(),
            # "days_left": days_left,
        }

        for organisation_user in landlord_users:
            already_sent = Notification.objects.filter(
                recipient_id=organisation_user.user_id,
                notification_type=NotificationType.CERTIFICATE_EXPIRING,
                data__alias=data["alias"],
                data__expiry_date=data["expiry_date"],
                data__days_left=days_left,
            ).exists()
            if already_sent:
                continue

            # Database + live notification
            create_notification_task.delay(
                recipient_id=organisation_user.user_id,
                notification_type=NotificationType.CERTIFICATE_EXPIRING,
                message=message,
                data=data,
                actor_id=None,
            )

            # Email notification
            send_certificate_expiry_email_task.delay(
                certificate.id,
                organisation_user.user_id,
                days_left,
            )

    except ComplianceAndCertification.DoesNotExist:
        logger.warning("Certificate %s no longer exists", certificate_id)
        return

    except Exception as exc:
        logger.exception(
            "Failed to notify landlords about certificate %s expiry", certificate_id
        )
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_certificate_expiry_email_task(self, certificate_id, user_id, days_left):
    try:
        certificate = ComplianceAndCertification.objects.select_related(
            "property", "organisation"
        ).get(pk=certificate_id)
        user = User.objects.get(pk=user_id, is_active=True)

        send_certificate_expiry_email(certificate, user, days_left)

    except Exception as exc:
        logger.exception(
            "Failed to send certificate expiry email for certificate %s", certificate_id
        )
        raise self.retry(exc=exc)