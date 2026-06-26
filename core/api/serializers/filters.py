from rest_framework import serializers

from apps.property.models import Property


class PropertyFilterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = [
            "id",
            "alias",
            "property_name",
        ]
