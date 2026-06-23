import os
from rest_framework import serializers
from apps.property.models import (
    Property,
    Mortgage,
    Tenant,
    TenantDocument,
    ComplianceAndCertification,
    UploadDocument,
)
from common.models import (
    Media,
    DocumentFile
)


class MediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = [
            "id",
            "image",
            "description",
        ]

class PropertySerializer(serializers.ModelSerializer):
    images = MediaSerializer(many=True, required=False)

    class Meta:
        model = Property
        fields = [
            "alias",
            "property_name",
            "address",
            "property_type",
            "status",
            "purchase_date",
            "purchase_price",
            "current_valuation",
            "product_type",
            "bedrooms",
            "bathrooms",
            "ownership_type",
            "ownership_percentage",
            "start_date",
            "end_date",
            "images",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        images_data = validated_data.pop("images", [])

        property_obj = Property.objects.create(**validated_data)

        for image_data in images_data:
            media = Media.objects.create(**image_data)
            property_obj.images.add(media)

        return property_obj

    def update(self, instance, validated_data):
        images_data = validated_data.pop("images", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if images_data is not None:
            instance.images.clear()
            for image_data in images_data:
                media = Media.objects.create(**image_data)
                instance.images.add(media)

        return instance


class MortgageSerializers(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    class Meta:
        model = Mortgage
        fields =[
            "alias",
            "property",
            "property_name",
            "lender_name",
            "mortgage_account_number",
            "mortgage_adviser",
            "interest_rate",
            "mortgage_product_type",
            "loan_amount",
            "start_date",
            "end_date",
            "monthly_payment",
            "outstanding_balance",
            "term",
            "early_repayment_charge",
            "renewal_date",
            "broker_notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
        ]

class TenantDocumentSerializer(serializers.ModelSerializer):
    files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False
    )
    file = serializers.FileField(
        read_only=False,
        required=False
    )

    class Meta:
        model = TenantDocument
        fields = [
            "alias",
            "files",
            "file",
            "description",
        ]
        read_only_fields = [
            "alias",
            "file",
        ]

class TenantSerializer(serializers.ModelSerializer):
    documents = TenantDocumentSerializer(many=True, read_only=True)
    properties = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Property.objects.all()
    )

    class Meta:
        model = Tenant
        fields = [
            "alias",
            "properties",
            "tenant_name",
            "contact_details",
            "tenancy_start_date",
            "tenancy_end_date",
            "rent_amount",
            "deposit_amount",
            "guarantor_details",
            "employment_details",
            "id_verification_records",
            "documents",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
        ]

class ComplianceAndCertificationSerializers(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)

    class Meta:
        model = ComplianceAndCertification
        fields = [
            "alias",
            "property",
            "property_name",
            "certificate_type",
            "issue_date",
            "expiry_date",
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

class DocumentFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentFile
        fields = [
            "id",
            "file",
            "description"
        ]


class UploadDocumentSerializer(serializers.ModelSerializer):
    files = DocumentFileSerializer(many=True, read_only=True)
    uploaded_files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
    )
    property_name = serializers.CharField(source="property.property_name", read_only=True)

    class Meta:
        model = UploadDocument
        fields = [
            "alias",
            "property",
            "property_name",
            "document_category",
            "document_name",
            "tags",
            "files",
            "uploaded_files",
        ]

    def validate_uploaded_files(self, files):
        allowed_extensions = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png"]
        limit = 50 * 1024 * 1024  # 50MB

        for file in files:
            if file.size > limit:
                raise serializers.ValidationError(f"{file.name} exceeds 50MB limit.")
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in allowed_extensions:
                raise serializers.ValidationError(f"{file.name} has an unsupported file type.")

        return files

    def create(self, validated_data):
        uploaded_files = validated_data.pop("uploaded_files", [])
        upload_document = UploadDocument.objects.create(**validated_data)

        for file in uploaded_files:
            doc_file = DocumentFile.objects.create(file=file)
            upload_document.files.add(doc_file)

        return upload_document

    def update(self, instance, validated_data):
        uploaded_files = validated_data.pop("uploaded_files", [])

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        for file in uploaded_files:
            doc_file = DocumentFile.objects.create(file=file)
            instance.files.add(doc_file)

        return instance