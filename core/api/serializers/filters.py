from rest_framework import serializers

from apps.property.models import Property, PropertyRoom


class PropertyFilterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = ["id", "alias", "property_name", "property_type"]


class PropertyRoomFilterSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyRoom
        fields = [
            "id",
            "alias",
            "room_name",
            "monthly_rent",
        ]
