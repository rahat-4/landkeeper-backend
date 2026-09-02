from rest_framework import serializers

from apps.authentication.models import Permission, User
from apps.property.models import Property, Mortgage

from common.serializers import (
    UserSlimSerializer,
    MediaSlimSerializer,
    PropertySlimSerializer,
    MortgageSlimSerializer,
)


class PermissionSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(
        slug_field="alias",
        queryset=User.objects.all(),
    )

    property = serializers.SlugRelatedField(
        slug_field="alias",
        queryset=Property.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )

    mortgage = serializers.SlugRelatedField(
        slug_field="alias",
        queryset=Mortgage.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )

    class Meta:
        model = Permission
        fields = [
            "alias",
            "user",
            "property",
            "mortgage",
            "can_view",
            "can_edit",
        ]

    def validate(self, attrs):
        user = attrs.get("user")
        property_obj = attrs.get("property")
        mortgage_obj = attrs.get("mortgage")

        # User explicitly changed can_view
        if "can_view" in attrs:
            can_view = attrs["can_view"]

            # If user turns view OFF,
            # automatically turn edit OFF.
            if can_view is False:
                attrs["can_edit"] = False

        # User explicitly changed can_edit
        if "can_edit" in attrs:
            can_edit = attrs["can_edit"]

            # If user turns edit ON,
            # automatically turn view ON.
            if can_edit is True:
                attrs["can_view"] = True

        # Property and mortgage cannot both be provided
        if property_obj is not None and mortgage_obj is not None:
            raise serializers.ValidationError(
                {
                    "non_field_errors": [
                        "Permission cannot be assigned to both property and mortgage."
                    ]
                }
            )

        # Duplicate property permission
        if property_obj is not None:
            queryset = Permission.objects.filter(
                user=user,
                property=property_obj,
            )

            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise serializers.ValidationError(
                    {
                        "property": [
                            "This user already has permission for this property."
                        ]
                    }
                )

        # Duplicate mortgage permission
        if mortgage_obj is not None:
            queryset = Permission.objects.filter(
                user=user,
                mortgage=mortgage_obj,
            )

            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise serializers.ValidationError(
                    {
                        "mortgage": [
                            "This user already has permission for this mortgage."
                        ]
                    }
                )

        # -----------------------------------------
        # Property can only belong to ONE user
        # -----------------------------------------
        if property_obj is not None:
            queryset = Permission.objects.filter(
                property=property_obj,
            )

            # Exclude current permission when updating
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                existing_permission = queryset.first()

                raise serializers.ValidationError(
                    {
                        "property": [
                            f"This property is already assigned to "
                            f"{existing_permission.user}."
                        ]
                    }
                )

        # -----------------------------------------
        # Mortgage can only belong to ONE user
        # -----------------------------------------
        if mortgage_obj is not None:
            queryset = Permission.objects.filter(
                mortgage=mortgage_obj,
            )

            # Exclude current permission when updating
            if self.instance:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                existing_permission = queryset.first()

                raise serializers.ValidationError(
                    {
                        "mortgage": [
                            f"This mortgage is already assigned to "
                            f"{existing_permission.user}."
                        ]
                    }
                )

        return attrs

    def to_representation(self, instance):
        rep = super().to_representation(instance)

        rep["user"] = UserSlimSerializer(
            instance.user,
            context={
                **self.context,
            },
        ).data

        return rep


class BulkPropertyPermissionSerializer(serializers.ModelSerializer):
    property = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
        required=False,
        write_only=True,
    )
    mortgage = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
        required=False,
        write_only=True,
    )
    can_view = serializers.BooleanField(default=False)
    can_edit = serializers.BooleanField(default=False)

    class Meta:
        model = Permission
        fields = [
            "alias",
            "property",
            "mortgage",
            "can_view",
            "can_edit",
        ]

    def to_representation(self, instance):
        rep = super().to_representation(instance)

        rep["property"] = PropertySlimSerializer(
            instance.property,
            context={
                **self.context,
            },
        ).data

        rep["mortgage"] = MortgageSlimSerializer(
            instance.mortgage,
            context={
                **self.context,
            },
        ).data

        return rep

    def validate(self, attrs):
        property_ids = attrs.get("property", [])
        mortgage_ids = attrs.get("mortgage", [])

        if not property_ids and not mortgage_ids:
            raise serializers.ValidationError(
                {"non_field_errors": ["This field is required."]}
            )

        if attrs.get("can_edit") and not attrs.get("can_view"):
            raise serializers.ValidationError(
                {"can_edit": "can_view must be true when can_edit is true."}
            )

        return attrs


class AvailablePropertySerializer(serializers.ModelSerializer):
    documents = MediaSlimSerializer(many=True, read_only=True)

    class Meta:
        model = Property
        fields = [
            "id",
            "alias",
            "property_name",
            "address",
            "property_owner",
            "company_name",
            "property_type",
            "status",
            "documents",
            "created_at",
            "updated_at",
        ]


class AvailableMortgageSerializer(serializers.ModelSerializer):
    property = PropertySlimSerializer(read_only=True)

    class Meta:
        model = Mortgage
        fields = [
            "alias",
            "lender_name",
            "epc_rating",
            "interest_rate_type",
            "interest_rate",
            "interest_rate_expiry_date",
            "outstanding_balance",
            "monthly_payment",
            "remaining_mortgage",
            "property",
        ]
