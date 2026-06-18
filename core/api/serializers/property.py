from rest_framework import serializers
from apps.property.models import Property, Mortgage
from common.models import Media


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
            "name",
            "address",
            "property_type",
            "purchase_date",
            "purchase_price",
            "current_valuation",
            "ownership_type",
            "ownership_percentage",
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
            "variable_type",
            "start_date",
            "end_date",
            "monthly_payment",
            "outstanding_balance",
            "early_repayment_charge",
            "renewal_date",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
        ]