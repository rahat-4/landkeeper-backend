import logging
import calendar
import re
from datetime import date

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from apps.organisation.enums import OrganisationRoleChoices
from apps.organisation.models import OrganisationUser
from apps.property.models import Tenant
from apps.tenant.enums import (
    RentPaymentStatusChoices,
    PaymentProviderChoices,
    MaintenanceStatus,
)
from apps.tenant.models import (
    PaymentMethod,
    RentPayment,
    CardPayment,
    MaintenanceRequest,
    MaintenanceRequestComment,
)
from common.models import DocumentFile
from common.serializers import TenantSlimSerializer

logger = logging.getLogger(__name__)


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = [
            "alias",
            "tenant",
            "organisation",
            "provider",
            "method_type",
            "provider_customer_id",
            "provider_mandate_id",
            "provider_payment_method_id",
            "status",
            "is_default",
            "card_last4",
            "card_brand",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "tenant",
            "organisation",
            "provider",
            "provider_customer_id",
            "provider_mandate_id",
            "provider_payment_method_id",
            "status",
            "is_default",
            "card_last4",
            "card_brand",
            "created_at",
            "updated_at",
        ]

class RentPaymentSerializer(serializers.ModelSerializer):
    payment_method = PaymentMethodSerializer(read_only=True)

    class Meta:
        model = RentPayment
        fields = [
            "alias",
            "tenant",
            "property",
            "organisation",
            "payment_method",
            "reference",
            "amount",
            "due_date",
            "paid_date",
            "status",
            "provider_payment_id",
            "receipt_file",
            "failure_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "tenant",
            "property",
            "organisation",
            "reference",
            "paid_date",
            "status",
            "provider_payment_id",
            "receipt_file",
            "failure_reason",
            "created_at",
            "updated_at",
        ]


class LandlordRentPaymentCreateSerializer(serializers.ModelSerializer):
    tenant = serializers.SlugRelatedField(
        slug_field="alias",
        queryset=Tenant.objects.all(),
        error_messages={
            "does_not_exist": "No tenant found with this identifier.",
            "invalid": "Invalid tenant identifier format.",
        },
    )

    class Meta:
        model = RentPayment
        fields = ["alias", "tenant", "amount", "due_date"]
        read_only_fields = ["alias"]

    def validate_tenant(self, tenant):
        request = self.context["request"]

        landlord_org_ids = list(
            request.user.organisation_users.values_list("organisation_id", flat=True)
        )

        if tenant.property.organisation_id not in landlord_org_ids:
            raise serializers.ValidationError("Not found.")

        return tenant

    def validate(self, attrs):
        tenant = attrs["tenant"]
        due_date = attrs["due_date"]

        exists = (
            RentPayment.objects.filter(tenant=tenant, due_date=due_date)
            .exclude(status=RentPaymentStatusChoices.FAILED)
            .exists()
        )

        if exists:
            raise serializers.ValidationError(
                {
                    "due_date": "A rent payment for this tenant and due date already exists."
                }
            )
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["tenant"] = TenantSlimSerializer(instance.tenant).data
        return data


class RentBalanceSummarySerializer(serializers.Serializer):
    current_rent_amount = serializers.SerializerMethodField()
    outstanding_balance = serializers.SerializerMethodField()
    next_due_date = serializers.SerializerMethodField()

    def get_current_rent_amount(self, tenant):
        return tenant.rent_amount or 0

    def get_outstanding_balance(self, tenant):
        rent_total = (
            RentPayment.objects.filter(tenant=tenant)
            .exclude(
                status__in=[
                    RentPaymentStatusChoices.CLEARED,
                    RentPaymentStatusChoices.REFUNDED,
                    RentPaymentStatusChoices.FAILED,
                ]
            )
            .aggregate(total=Sum("amount"))["total"]
            or 0
        )

        existing_due_dates = set(
            RentPayment.objects.filter(tenant=tenant).values_list("due_date", flat=True)
        )

        orphan_card_total = (
            CardPayment.objects.filter(tenant=tenant)
            .exclude(due_date__in=existing_due_dates)
            .exclude(
                status__in=[
                    RentPaymentStatusChoices.CLEARED,
                    RentPaymentStatusChoices.REFUNDED,
                    RentPaymentStatusChoices.FAILED,
                ]
            )
            .aggregate(total=Sum("amount"))["total"]
            or 0
        )

        return rent_total + orphan_card_total

    def get_next_due_date(self, tenant):
        today = timezone.localdate()

        # Tenancy already ended — no next due date.
        if tenant.tenancy_end_date and tenant.tenancy_end_date < today:
            return None

        next_payment = (
            RentPayment.objects.filter(tenant=tenant, due_date__gte=today)
            .exclude(status=RentPaymentStatusChoices.CLEARED)
            .order_by("due_date")
            .first()
        )
        if next_payment:
            return next_payment.due_date

        last_payment = (
            RentPayment.objects.filter(tenant=tenant).order_by("-due_date").first()
        )

        if last_payment:
            rent_day = last_payment.due_date.day
            year, month = last_payment.due_date.year, last_payment.due_date.month
        elif tenant.tenancy_start_date:
            rent_day = tenant.tenancy_start_date.day
            year, month = today.year, today.month
        else:
            return None

        next_date = date(
            year, month, min(rent_day, calendar.monthrange(year, month)[1])
        )
        while next_date <= today:
            month += 1
            if month > 12:
                month = 1
                year += 1
            last_day = calendar.monthrange(year, month)[1]
            next_date = date(year, month, min(rent_day, last_day))

        if tenant.tenancy_end_date and next_date > tenant.tenancy_end_date:
            return None

        return next_date


class DirectDebitSetupRequestSerializer(serializers.Serializer):
    success_redirect_url = serializers.URLField()


class DirectDebitCompleteRequestSerializer(serializers.Serializer):
    redirect_flow_id = serializers.CharField()
    session_token = serializers.CharField()


class DirectDebitPaymentRequestSerializer(serializers.Serializer):
    _BLOCKED_FOR_NEW_ATTEMPT_STATUSES = (
        RentPaymentStatusChoices.CLEARED,
        RentPaymentStatusChoices.PROCESSING,
    )

    due_date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)

    def validate(self, attrs):
        request = self.context["request"]
        due_date = attrs["due_date"]
        amount = attrs["amount"]

        rent_payment = (
            RentPayment.objects.filter(tenant_id=request.user.id, due_date=due_date)
            .exclude(status__in=self._BLOCKED_FOR_NEW_ATTEMPT_STATUSES)
            .order_by("-created_at")
            .first()
        )

        if rent_payment is None:
            raise serializers.ValidationError(
                {"due_date": "No rent payment found for this due date."}
            )

        if amount != rent_payment.amount:
            raise serializers.ValidationError(
                {
                    "amount": f"Amount must match the rent payment amount of £{rent_payment.amount}."
                }
            )

        payment_method = (
            PaymentMethod.objects.filter(
                tenant=request.user,
                provider=PaymentProviderChoices.GOCARDLESS,
                is_default=True,
            )
            .exclude(provider_mandate_id__isnull=True)
            .exclude(provider_mandate_id="")
            .first()
        )

        if not payment_method:
            raise serializers.ValidationError(
                "No active direct debit mandate found. Please set up direct debit first."
            )

        attrs["rent_payment"] = rent_payment
        attrs["payment_method"] = payment_method
        return attrs


class CardPaymentRequestSerializer(serializers.Serializer):
    due_date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    payment_method_id = serializers.CharField(required=False, allow_blank=True)


class CardPaymentSerializer(serializers.ModelSerializer):
    payment_method = PaymentMethodSerializer(read_only=True)

    class Meta:
        model = CardPayment
        fields = [
            "alias",
            "payment_method",
            "amount",
            "due_date",
            "status",
            "provider_payment_id",
            "failure_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DocumentFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentFile
        fields = ["id", "file"]


class MaintenanceRequestSerializer(serializers.ModelSerializer):
    documents = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        write_only=True,
    )
    removed_document_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )

    request_id = serializers.SerializerMethodField()
    tenant = TenantSlimSerializer(read_only=True)
    property = serializers.SerializerMethodField()
    organisation = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceRequest
        fields = [
            "alias",
            "request_id",
            "tenant",
            "property",
            "organisation",
            "issue",
            "category",
            "current_status",
            "is_emergency",
            "notes",
            "documents",
            "removed_document_ids",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "tenant",
            "property",
            "organisation",
            "created_at",
            "updated_at",
        ]

    def get_request_id(self, obj):
        return f"MR-{obj.id:08d}"

    def get_property(self, obj):
        if not obj.property:
            return None
        return f"{obj.property.property_name} - {obj.property.address}"

    def get_organisation(self, obj):
        return obj.organisation.name if obj.organisation else None

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep["documents"] = DocumentFileSerializer(
            instance.documents.all(), many=True, context=self.context
        ).data
        return rep

    def validate(self, attrs):
        user = self.context["request"].user

        if isinstance(user, Tenant):
            attrs.pop("current_status", None)
            return attrs

        is_landlord = OrganisationUser.objects.filter(
            user=user,
            role=OrganisationRoleChoices.LANDLORD,
        ).exists()

        if is_landlord:
            allowed_fields = {"current_status"}
            invalid_fields = set(attrs.keys()) - allowed_fields
            if invalid_fields:
                raise serializers.ValidationError(
                    {
                        "detail": "Landlords can only update the maintenance request status."
                    }
                )
        return attrs

    def create(self, validated_data):
        new_files = validated_data.pop("documents", [])
        instance = super().create(validated_data)
        for f in new_files:
            doc = DocumentFile.objects.create(file=f)
            instance.documents.add(doc)
        return instance

    def update(self, instance, validated_data):
        for field in ("tenant", "property", "organisation"):
            validated_data.pop(field, None)

        new_files = validated_data.pop("documents", [])
        removed_ids = validated_data.pop("removed_document_ids", [])

        with transaction.atomic():
            instance = super().update(instance, validated_data)

            if removed_ids:
                docs_to_remove = instance.documents.filter(id__in=removed_ids)
                instance.documents.remove(*docs_to_remove)
                docs_to_remove.delete()

            for f in new_files:
                doc = DocumentFile.objects.create(file=f)
                instance.documents.add(doc)

        return instance


class MaintenanceRequestCommentAuthorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    email = serializers.EmailField()
    type = serializers.SerializerMethodField()

    def get_name(self, obj):
        return obj.get_full_name()

    def get_type(self, obj):
        return "tenant" if isinstance(obj, Tenant) else "staff"


class MaintenanceRequestCommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    documents = DocumentFileSerializer(many=True, read_only=True)
    upload_files = serializers.ListField(
        child=serializers.FileField(), write_only=True, required=False
    )

    class Meta:
        model = MaintenanceRequestComment
        fields = [
            "id",
            "alias",
            "message",
            "parent",
            "author",
            "documents",
            "upload_files",
            "replies",
            "created_at",
        ]
        read_only_fields = ["id", "alias", "author", "created_at"]

    def get_author(self, obj):
        return MaintenanceRequestCommentAuthorSerializer(obj.author).data

    def get_replies(self, obj):
        replies = obj.replies.all().order_by("created_at")
        return MaintenanceRequestCommentSerializer(
            replies, many=True, context=self.context
        ).data

    def validate(self, attrs):
        parent = attrs.get("parent")
        maintenance_request = self.context.get("maintenance_request")
        if (
            parent
            and maintenance_request
            and parent.maintenance_request_id != maintenance_request.id
        ):
            raise serializers.ValidationError(
                {
                    "parent": "Parent comment must belong to the same maintenance request."
                }
            )
        return attrs

    def create(self, validated_data):
        upload_files = validated_data.pop("upload_files", [])
        comment = MaintenanceRequestComment.objects.create(**validated_data)
        documents = [DocumentFile.objects.create(file=f) for f in upload_files]
        if documents:
            comment.documents.add(*documents)
        return comment

    def update(self, instance, validated_data):
        upload_files = validated_data.pop("upload_files", [])
        instance = super().update(instance, validated_data)
        if upload_files:
            for old_document in instance.documents.all():
                instance.documents.remove(old_document)
                old_document.file.delete(save=False)
                old_document.delete()
            new_documents = [DocumentFile.objects.create(file=f) for f in upload_files]
            instance.documents.add(*new_documents)
        return instance
