import os
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.contrib.auth.hashers import make_password
import re
from rest_framework import serializers
from apps.authentication.models import InviteUser
from apps.organisation.enums import OrganisationRoleChoices
from apps.organisation.utils import get_request_organisation
from apps.property.enums import PropertyOwnerType
from apps.property.models import (
    Property,
    Mortgage,
    Tenant,
    ComplianceAndCertification,
    UploadDocument,
    Finance,
    PropertyOwnership,
)
from common.models import Media, DocumentFile
from common.serializers import (
    PropertySlimSerializer,
    TenantSlimSerializer,
    UserSlimSerializer,
)
from django.db import transaction

User = get_user_model()


class MediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = [
            "id",
            "image",
            "description",
        ]


class DocumentFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentFile
        fields = ["id", "file", "description"]


class PropertyOwnershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyOwnership
        fields = [
            "shareholder_name",
            "owner_name",
            "share_percentage",
        ]
        extra_kwargs = {
            "owner_name": {"required": False, "allow_null": True, "allow_blank": True},
            "shareholder_name": {
                "required": False,
                "allow_null": True,
                "allow_blank": True,
            },
            "share_percentage": {"required": False, "allow_null": True},
        }

    def to_representation(self, instance):
        rep = {}
        property_owner = getattr(instance.property, "property_owner", None)

        if property_owner == PropertyOwnerType.COMPANY:
            rep["shareholder_name"] = instance.shareholder_name
            rep["share_percentage"] = instance.share_percentage
        else:
            rep["owner_name"] = instance.owner_name

        return rep


class PropertySerializer(serializers.ModelSerializer):
    documents_data = serializers.ListField(
        child=serializers.ImageField(), required=False, write_only=True
    )
    documents = MediaSerializer(many=True, read_only=True)
    shareholder = PropertyOwnershipSerializer(many=True, required=False)
    landlord = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = [
            "id",
            "alias",
            "can_edit",
            "landlord",
            "property_name",
            "property_owner",
            "company_name",
            "property_type",
            "status",
            "address",
            "purchase_price",
            "current_value",
            "purchase_date",
            "year_built",
            "property_tenure",
            "remaining_lease_term",
            "monthly_service_charge",
            "annual_ground_rent",
            "bedrooms",
            "bathrooms",
            "council_tax_band",
            "local_authority",
            "monthly_rental_income",
            "notes",
            "shareholder",
            "documents",
            "documents_data",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "landlord",
            "created_at",
            "updated_at",
        ]

    def get_landlord(self, obj):
        organisation_user = (
            obj.organisation.organisation_users.select_related("user")
            .filter(role=OrganisationRoleChoices.LANDLORD)
            .first()
        )
        if organisation_user is None:
            return None

        user = organisation_user.user
        return {
            "id": user.id,
            "full_name": user.get_full_name(),
            "email": user.email,
            "phone": user.phone,
            "profile_image": user.profile_image.url if user.profile_image else None,
            "current_address": user.current_address,
            "ni_number": user.ni_number,
            "utr_number": user.utr_number,
        }

    def get_can_edit(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            return False

        # Superadmin can always edit
        if user.is_superuser:
            return True

        organisation = user.get_organisation()

        if not organisation:
            return False

        if user.organisation_users.filter(
            organisation=organisation,
            role__in=[OrganisationRoleChoices.LANDLORD, OrganisationRoleChoices.ADMIN],
        ).exists():
            return True

        return user.permissions.filter(
            property=obj,
            organisation=organisation,
            can_edit=True,
        ).exists()

    def validate(self, attrs):
        property_owner = attrs.get(
            "property_owner",
            getattr(self.instance, "property_owner", None),
        )
        shareholder = attrs.get("shareholder")

        if shareholder:
            if property_owner == PropertyOwnerType.COMPANY:
                for owner in shareholder:
                    if owner.get("share_percentage") in (None, ""):
                        raise serializers.ValidationError(
                            {
                                "shareholder": [
                                    "share_percentage is required when property_owner is COMPANY."
                                ]
                            }
                        )
                    owner["owner_name"] = None
            elif property_owner == PropertyOwnerType.OWNER:
                for owner in shareholder:
                    owner["share_percentage"] = None
                    owner["shareholder_name"] = None

        return attrs

    MULTI_VALUE_FIELDS = {"documents_data"}

    def to_internal_value(self, data):
        if hasattr(data, "getlist"):
            plain_data = {}
            for key in data.keys():
                values = data.getlist(key)
                if key in self.MULTI_VALUE_FIELDS:
                    plain_data[key] = values
                else:
                    plain_data[key] = values if len(values) > 1 else values[0]
        else:
            plain_data = dict(data)

        shareholder = []
        index = 0
        while True:
            owner_name_key = f"shareholder[{index}].owner_name"
            shareholder_name_key = f"shareholder[{index}].shareholder_name"
            share_percentage_key = f"shareholder[{index}].share_percentage"

            if (
                owner_name_key not in plain_data
                and shareholder_name_key not in plain_data
                and share_percentage_key not in plain_data
            ):
                break

            shareholder.append(
                {
                    "owner_name": plain_data.pop(owner_name_key, None),
                    "shareholder_name": plain_data.pop(shareholder_name_key, None),
                    "share_percentage": plain_data.pop(share_percentage_key, None),
                }
            )
            index += 1

        if shareholder:
            plain_data["shareholder"] = shareholder

        elif "shareholder" not in plain_data and self.instance is None:
            plain_data["shareholder"] = []

        return super().to_internal_value(plain_data)

    def create(self, validated_data):
        documents_data = validated_data.pop("documents_data", [])
        print("PropertySerializer.create documents_data:", documents_data)
        shareholder = validated_data.pop("shareholder", [])

        property_obj = Property.objects.create(**validated_data)

        documents = [Media.objects.create(image=d) for d in documents_data]
        property_obj.documents.set(documents)

        for owner in shareholder:
            PropertyOwnership.objects.create(property=property_obj, **owner)

        return property_obj

    def update(self, instance, validated_data):
        documents_data = validated_data.pop("documents_data", None)
        shareholder = validated_data.pop("shareholder", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if documents_data is not None:
            instance.documents.all().delete()
            documents = [Media.objects.create(image=d) for d in documents_data]
            instance.documents.set(documents)

        if shareholder is not None:
            instance.shareholder.all().delete()
            for owner in shareholder:
                PropertyOwnership.objects.create(property=instance, **owner)

        return instance


class MortgageSerializers(serializers.ModelSerializer):
    mortgage_documents = serializers.ListField(
        child=serializers.FileField(), write_only=True, required=False
    )
    uploaded_documents = DocumentFileSerializer(
        source="mortgage_documents", many=True, read_only=True
    )
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Mortgage
        fields = [
            "alias",
            "can_edit",
            "property",
            "lender_name",
            "interest_rate_type",
            "interest_rate",
            "interest_rate_expiry_date",
            "outstanding_balance",
            "monthly_payment",
            "remaining_mortgage",
            "epc_rating",
            "epc_certificate_expiry_date",
            "notes",
            "mortgage_documents",
            "uploaded_documents",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["property"] = PropertySlimSerializer(instance.property).data
        return representation

    def _validate_mortgage_files(self, files):
        allowed_extensions = [
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".jpg",
            ".jpeg",
            ".png",
        ]
        limit = 50 * 1024 * 1024
        for file in files:
            if file.size > limit:
                raise serializers.ValidationError(f"{file.name} exceeds 50MB limit.")
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in allowed_extensions:
                raise serializers.ValidationError(
                    f"{file.name} has an unsupported file type."
                )

    def get_can_edit(self, obj):
        request = self.context.get("request")
        user = getattr(request, "user", None)

        # Superadmin can always edit
        if user.is_superuser:
            return True

        if not user or not user.is_authenticated:
            return False

        organisation = user.get_organisation()

        if not organisation:
            return False

        if user.organisation_users.filter(
            organisation=organisation,
            role__in=[OrganisationRoleChoices.LANDLORD, OrganisationRoleChoices.ADMIN],
        ).exists():
            return True

        return user.permissions.filter(
            mortgage=obj,
            organisation=organisation,
            can_edit=True,
        ).exists()

    def create(self, validated_data):
        uploaded_files = validated_data.pop("mortgage_documents", [])
        self._validate_mortgage_files(uploaded_files)
        mortgage = Mortgage.objects.create(**validated_data)

        for file in uploaded_files:
            doc_file = DocumentFile.objects.create(file=file)
            mortgage.mortgage_documents.add(doc_file)
        return mortgage

    def update(self, instance, validated_data):
        uploaded_files = validated_data.pop("mortgage_documents", None)

        if uploaded_files is not None:
            self._validate_mortgage_files(uploaded_files)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if uploaded_files is not None:
            instance.mortgage_documents.all().delete()

            for file in uploaded_files:
                doc_file = DocumentFile.objects.create(file=file)
                instance.mortgage_documents.add(doc_file)

        return instance


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "alias",
            "avatar",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "email",
            "phone",
            "image",
            "rent_amount",
            "deposit",
            "tenancy_start_date",
            "tenancy_end_date",
            "employment_details",
            "guarantor_name",
            "notes",
            "is_active",
            "is_password_set",
            "property",
            "created_at",
        ]
        read_only_fields = [
            "alias",
        ]

    def validate_email(self, value):
        if self.instance:
            organisation = self.instance.organisation
        else:
            organisation = get_request_organisation(self.context.get("request"))

        tenant_queryset = Tenant.objects.filter(
            organisation=organisation,
            email=value,
        )

        # Exclude current tenant during update
        if self.instance:
            tenant_queryset = tenant_queryset.exclude(pk=self.instance.pk)

        if (
            tenant_queryset.exists()
            or User.objects.filter(email=value).exists()
            or InviteUser.objects.filter(email=value).exists()
        ):
            raise serializers.ValidationError("Email is already in use.")

        return value

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["property"] = PropertySlimSerializer(instance.property).data
        return representation

    def create(self, validated_data):
        validated_data["password"] = make_password(None)
        return super().create(validated_data)


class ComplianceAndCertificationSerializers(serializers.ModelSerializer):
    class Meta:
        model = ComplianceAndCertification
        fields = [
            "alias",
            "property",
            "certificate_type",
            "issue_date",
            "expiry_date",
            "certificate_number",
            "issued_by",
            "certificate_file",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["property"] = PropertySlimSerializer(instance.property).data
        return representation


class ComplianceShareSerializer(serializers.Serializer):
    tenant = serializers.ListField(child=serializers.CharField(), allow_empty=False)

    def validate_tenant(self, value):
        seen = set()
        deduped = [x for x in value if not (x in seen or seen.add(x))]
        return deduped


class UploadDocumentSerializer(serializers.ModelSerializer):
    files = DocumentFileSerializer(many=True, read_only=True)
    uploaded_files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = UploadDocument
        fields = [
            "alias",
            "property",
            "document_category",
            "document_name",
            "tags",
            "files",
            "uploaded_files",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["alias", "created_at", "updated_at"]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["property"] = PropertySlimSerializer(instance.property).data
        return representation

    def _validate_files(self, files):
        allowed_extensions = [
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".jpg",
            ".jpeg",
            ".png",
        ]
        limit = 50 * 1024 * 1024
        for file in files:
            if file.size > limit:
                raise serializers.ValidationError(f"{file.name} exceeds 50MB limit.")
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in allowed_extensions:
                raise serializers.ValidationError(
                    f"{file.name} has an unsupported file type."
                )

    def create(self, validated_data):
        uploaded_files = validated_data.pop("uploaded_files", [])
        self._validate_files(uploaded_files)
        upload_document = UploadDocument.objects.create(**validated_data)

        for file in uploaded_files:
            doc_file = DocumentFile.objects.create(file=file)
            upload_document.files.add(doc_file)
        return upload_document

    def update(self, instance, validated_data):
        uploaded_files = validated_data.pop("uploaded_files", None)

        if uploaded_files is not None:
            self._validate_files(uploaded_files)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if uploaded_files is not None:
            instance.files.all().delete()

            for file in uploaded_files:
                doc_file = DocumentFile.objects.create(file=file)
                instance.files.add(doc_file)

        return instance


class FinanceSerializer(serializers.ModelSerializer):
    receipt_files = DocumentFileSerializer(many=True, read_only=True, source="receipt")
    uploaded_receipt = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Finance
        fields = [
            "alias",
            "property",
            "type",
            "category",
            "amount",
            "date",
            "description",
            "receipt_files",
            "uploaded_receipt",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
        ]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation["property"] = PropertySlimSerializer(instance.property).data
        return representation

    def validate_uploaded_receipt(self, receipt):
        allowed_extensions = [
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".jpg",
            ".jpeg",
            ".png",
        ]
        limit = 50 * 1024 * 1024

        for file in receipt:
            if file.size > limit:
                raise serializers.ValidationError(f"{file.name} exceeds 50MB limit.")
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in allowed_extensions:
                raise serializers.ValidationError(
                    f"{file.name} has an unsupported file type."
                )

        return receipt

    def create(self, validated_data):
        uploaded_receipt = validated_data.pop("uploaded_receipt", [])
        finance = Finance.objects.create(**validated_data)

        for file in uploaded_receipt:
            doc_file = DocumentFile.objects.create(file=file)
            finance.receipt.add(doc_file)
        return finance

    def update(self, instance, validated_data):
        uploaded_receipt = validated_data.pop("uploaded_receipt", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if uploaded_receipt is not None:
            # Delete old DocumentFile objects
            instance.receipt.all().delete()

            # Add new files
            for file in uploaded_receipt:
                doc_file = DocumentFile.objects.create(file=file)
                instance.receipt.add(doc_file)

        return instance


class PropertyOnboardingSerializer(serializers.Serializer):
    STEP_ORDER = ["property", "mortgage", "tenant", "compliance", "upload_document"]

    STEP_SERIALIZERS = {
        "property": PropertySerializer,
        "mortgage": MortgageSerializers,
        "tenant": TenantSerializer,
        "compliance": ComplianceAndCertificationSerializers,
        "upload_document": UploadDocumentSerializer,
    }

    MULTI_VALUE_FIELDS = {
        "property": {"documents_data"},
        "mortgage": {"mortgage_documents"},
        "upload_document": {"uploaded_files"},
    }

    property = serializers.DictField(required=False)
    mortgage = serializers.DictField(required=False)
    tenant = serializers.DictField(required=False)
    compliance = serializers.DictField(required=False)
    upload_document = serializers.DictField(required=False)

    def to_internal_value(self, data):
        if any(
            isinstance(data.get(step), dict)
            for step in self.STEP_ORDER
            if hasattr(data, "get")
        ):
            return super().to_internal_value(data)

        nested = {}
        keys = data.keys() if hasattr(data, "keys") else []

        for key in keys:
            for step in self.STEP_ORDER:
                prefix = f"{step}_"
                if key.startswith(prefix):
                    field_name = key[len(prefix) :]

                    if hasattr(data, "getlist"):
                        values = data.getlist(key)
                        is_multi = field_name in self.MULTI_VALUE_FIELDS.get(
                            step, set()
                        )
                        value = values if (is_multi or len(values) > 1) else values[0]
                    else:
                        value = data.get(key)

                    if isinstance(value, str) and value.strip() == "":
                        value = None

                    ownership_match = re.match(
                        r"shareholder\[(\d+)\]\.(\w+)$",
                        field_name,
                    )

                    if ownership_match:
                        index = int(ownership_match.group(1))
                        owner_field = ownership_match.group(2)

                        property_data = nested.setdefault(step, {})
                        shareholder = property_data.setdefault("shareholder", [])

                        while len(shareholder) <= index:
                            shareholder.append({})

                        shareholder[index][owner_field] = value
                    else:
                        nested.setdefault(step, {})[field_name] = value

                    break

        if nested:
            self.initial_data = nested
            return super().to_internal_value(nested)

        return super().to_internal_value(data)

    def validate(self, attrs):
        if not any(key in self.initial_data for key in self.STEP_ORDER):
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "At least one of property/mortgage/tenant/compliance/upload_document is required."
                    ]
                }
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        organisation = self.context.get("organisation")

        if not organisation:
            raise serializers.ValidationError(
                {"organisation": ["Organisation context is required."]}
            )

        property_obj = None
        results = {}

        for step_name in self.STEP_ORDER:
            if step_name not in validated_data:
                continue

            serializer_class = self.STEP_SERIALIZERS[step_name]
            payload = dict(validated_data[step_name])
            print(
                f"[{step_name}] documents_data present:",
                "documents_data" in payload,
                payload.get("documents_data"),
            )

            if step_name != "property":
                if property_obj is None:
                    raise serializers.ValidationError(
                        {"property": ["Property must be created first in this batch."]}
                    )
                payload["property"] = property_obj.pk

            serializer = serializer_class(data=payload, context=self.context)
            serializer.is_valid(raise_exception=True)

            try:
                instance = serializer.save(organisation=organisation)
            except DjangoValidationError as e:
                if hasattr(e, "message_dict"):
                    messages = []
                    for field_messages in e.message_dict.values():
                        messages.extend(field_messages)
                else:
                    messages = e.messages
                raise serializers.ValidationError({step_name: messages})
            except IntegrityError:
                raise serializers.ValidationError(
                    {step_name: ["A record with these details already exists."]}
                )

            if step_name == "property":
                property_obj = instance

            results[step_name] = serializer_class(instance, context=self.context).data

        return results
