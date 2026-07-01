import os
from rest_framework import serializers
from apps.property.models import (
    Property,
    Mortgage,
    Tenant,
    ComplianceAndCertification,
    UploadDocument,
    Finance,
)
from common.models import Media, DocumentFile
from common.serializers import PropertySlimSerializer


class MediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = [
            "id",
            "image",
            "description",
        ]


class PropertySerializer(serializers.ModelSerializer):
    documents_data = serializers.ListField(
        child=serializers.ImageField(), required=False, write_only=True
    )
    documents = MediaSerializer(many=True, read_only=True)

    class Meta:
        model = Property
        fields = [
            "id",
            "alias",
            "property_name",
            "property_type",
            "status",
            "address",
            "purchase_price",
            "current_value",
            "purchase_date",
            "bedrooms",
            "bathrooms",
            "rent_per_month",
            "notes",
            "documents",
            "documents_data",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        documents_data = validated_data.pop("documents_data", [])

        property_obj = Property.objects.create(**validated_data)

        documents = [
            Media.objects.create(image=document) for document in documents_data
        ]

        property_obj.documents.set(documents)

        return property_obj

    def update(self, instance, validated_data):
        documents_data = validated_data.pop("documents_data", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()

        if documents_data is not None:
            instance.documents.all().delete()

            documents = [
                Media.objects.create(image=document) for document in documents_data
            ]

            instance.documents.set(documents)

        return instance


class MortgageSerializers(serializers.ModelSerializer):
    class Meta:
        model = Mortgage
        fields = [
            "alias",
            "property",
            "lender_name",
            "product_type",
            "interest_rate",
            "loan_amount",
            "outstanding_balance",
            "monthly_payment",
            "term",
            "start_date",
            "end_date",
            "broker_notes",
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


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "alias",
            "avatar",
            "first_name",
            "last_name",
            "email",
            "phone",
            "rent_amount",
            "deposit",
            "tenancy_start_date",
            "tenancy_end_date",
            "employment_details",
            "guarantor_name",
            "notes",
            "property",
        ]
        read_only_fields = [
            "alias",
        ]


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


class DocumentFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentFile
        fields = ["id", "file", "description"]


class UploadDocumentSerializer(serializers.ModelSerializer):
    files = DocumentFileSerializer(many=True, read_only=True)
    property_name = serializers.CharField(
        source="property.property_name", read_only=True
    )

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
        ]

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
        uploaded_files = validated_data.pop("uploaded_files", [])
        self._validate_files(uploaded_files)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

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
        uploaded_receipt = validated_data.pop("uploaded_receipt", [])

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        for file in uploaded_receipt:
            doc_file = DocumentFile.objects.create(file=file)
            instance.receipt.add(doc_file)
        return instance
