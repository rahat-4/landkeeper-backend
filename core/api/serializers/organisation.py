from rest_framework import serializers
from apps.organisation.models import Organisation, OrganisationUser, User
from api.serializers.auth import UserProfileSerializer


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = [
            "slug",
            "name",
            "description",
            "logo",
            "profile_image",
            "primary_mobile",
            "other_contact",
            "contact_person",
            "website",
            "address",
            "is_active",
            "created_at",
            "updated_at",
        ]


class OrganisationUserMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "profile_image"]


class OrganisationMinimalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ["slug", "name"]


class OrganisationUserSerializer(serializers.ModelSerializer):
    user = OrganisationUserMinimalSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source="user", write_only=True
    )
    organisation = OrganisationMinimalSerializer(read_only=True)

    class Meta:
        model = OrganisationUser
        fields = [
            "id",
            "user",
            "user_id",
            "organisation",
            "role",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "organisation", "created_at", "updated_at"]

    def validate(self, attrs):
        organisation = self.context.get("organisation") or getattr(
            self.instance, "organisation", None
        )
        user = attrs.get("user", getattr(self.instance, "user", None))
        if organisation and user:
            qs = OrganisationUser.objects.filter(user=user, organisation=organisation)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    {"user": "This user is already a member of this organisation."}
                )
        return attrs

    def create(self, validated_data):
        organisation = self.context["organisation"]
        return OrganisationUser.objects.create(
            organisation=organisation, **validated_data
        )
