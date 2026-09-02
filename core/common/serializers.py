from django.contrib.auth import get_user_model

from rest_framework import serializers

from apps.property.models import Property, Mortgage, DocumentFile
from apps.tenant.models import Tenant

from .models import Media

User = get_user_model()


class UserSlimSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="get_full_name", read_only=True)
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["profile_image", "name", "email", "phone", "role"]

    def get_role(self, obj):
        organisation_user = obj.organisation_users.first()
        if organisation_user:
            return organisation_user.role
        return None


class MortgageSlimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mortgage
        fields = ["id", "alias", "lender_name", "epc_rating"]


class MediaSlimSerializer(serializers.ModelSerializer):
    class Meta:
        model = Media
        fields = [
            "id",
            "image",
            "description",
        ]


class PropertySlimSerializer(serializers.ModelSerializer):
    documents = MediaSlimSerializer(many=True, read_only=True)

    class Meta:
        model = Property
        fields = ["id", "alias", "property_name", "address", "status", "property_type", "documents"]


class DocumentFileSlimSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentFile
        fields = ["id", "file", "description"]


class TenantSlimSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = Tenant
        fields = ["alias", "name", "email", "phone", "avatar"]
