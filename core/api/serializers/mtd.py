from django.utils import timezone

from rest_framework import serializers

from common.models import DocumentFile
from common.serializers import DocumentFileSlimSerializer

from apps.mtd.enums import MTDQuarter
from apps.mtd.models import (
    MTD_FIRST_TAX_YEAR,
    MTDFinanceCost,
    MTDReport,
    get_period_for_date,
)
from apps.mtd.services import calculate_report_summary
from apps.property.models import Finance, Property


class MTDReportSerializer(serializers.ModelSerializer):
    current_tax_year = serializers.SerializerMethodField()
    current_quarter = serializers.SerializerMethodField()
    properties = serializers.SlugRelatedField(
        slug_field="alias", many=True, read_only=True
    )

    class Meta:
        model = MTDReport
        fields = [
            "alias",
            "current_tax_year",
            "current_quarter",
            "tax_year",
            "quarter",
            "properties",
        ]
        read_only_fields = fields

    def get_current_tax_year(self, obj):
        current_tax_year, current_quarter = get_period_for_date(timezone.localdate())

        return current_tax_year

    def get_current_quarter(self, obj):
        current_year, current_quarter = get_period_for_date(timezone.localdate())

        return current_quarter

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if self.context.get("include_summary"):
            representation.update(calculate_report_summary(instance))
        return representation


class MTDReportPeriodSerializer(serializers.Serializer):
    tax_year = serializers.IntegerField(
        min_value=MTD_FIRST_TAX_YEAR, max_value=2100, required=False
    )
    quarter = serializers.ChoiceField(choices=MTDQuarter.choices, required=False)


class MTDPropertySelectionSerializer(serializers.Serializer):
    properties = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)

    def validate_properties(self, aliases):
        report = self.context["report"]
        aliases = set(aliases)
        properties = list(
            Property.objects.filter(organisation=report.organisation, alias__in=aliases)
        )
        missing = aliases - {property.alias for property in properties}
        if missing:
            raise serializers.ValidationError(
                f"Properties not found: {', '.join(map(str, missing))}"
            )
        return properties


class MTDIncomeExpenseSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(
        source="property.property_name", read_only=True
    )

    class Meta:
        model = Finance
        fields = [
            "alias",
            "property_name",
            "type",
            "category",
            "amount",
            "date",
        ]
        read_only_fields = fields


class MTDFinanceCostSerializer(serializers.ModelSerializer):
    alias = serializers.CharField(source="mortgage.alias", read_only=True)
    property_name = serializers.CharField(
        source="mortgage.property.property_name",
        read_only=True,
    )
    lender_name = serializers.CharField(
        source="mortgage.lender_name",
        read_only=True,
    )
    monthly_payment = serializers.DecimalField(
        source="mortgage.monthly_payment",
        max_digits=10,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    evidence = DocumentFileSlimSerializer(many=True, read_only=True)
    evidence_files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = MTDFinanceCost
        fields = [
            "alias",
            "property_name",
            "lender_name",
            "monthly_payment",
            "notes",
            "evidence",
            "evidence_files",
        ]

    def update(self, instance, validated_data):
        evidence_files = validated_data.pop("evidence_files", [])

        # Update notes and other permitted model fields.
        instance = super().update(instance, validated_data)

        # Save each uploaded file as a DocumentFile.
        for uploaded_file in evidence_files:
            document = DocumentFile.objects.create(
                # Replace `file` with your actual upload field.
                file=uploaded_file,
            )
            instance.evidence.add(document)

        return instance


class MTDReportDeclarationSerializer(serializers.Serializer):
    confirmed_all_properties_included = serializers.BooleanField()
    confirmed_entries_checked = serializers.BooleanField()
    confirmed_items_flagged = serializers.BooleanField()
    confirmed_by_name = serializers.CharField(max_length=255)
    confirmed_at = serializers.DateField()
    review_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not all(
            [
                attrs["confirmed_all_properties_included"],
                attrs["confirmed_entries_checked"],
                attrs["confirmed_items_flagged"],
            ]
        ):
            raise serializers.ValidationError(
                "All declarations must be ticked before downloading the summary."
            )
        return attrs
