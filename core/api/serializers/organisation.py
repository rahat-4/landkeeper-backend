from rest_framework import serializers
from apps.organisation.models import (
    Organisation,
    OrganisationUser
)

class OrganisationUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganisationUser
        fields = [
            "id",
            "role",
            "designation",
            "official_email",
            "official_phone",
            "permanent_address",
            "present_address",
            "dob",
            "gender",
            "joining_date",
            "source",
            "other_source",
            "note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user",
            "role",
            "created_at",
            "updated_at",
        ]


class OrganisationSerializer(serializers.ModelSerializer):
    user = OrganisationUserSerializer(
        source="organisation_users",
        many=True,
        read_only=True,
    )
    user_info = OrganisationUserSerializer(
        write_only=True,
        required=True,
    )

    class Meta:
        model = Organisation
        fields = [
            "slug",
            "name",
            "description",
            "email",
            "logo",
            "profile_image",
            "primary_mobile",
            "other_contact",
            "contact_person",
            "contact_person_designation",
            "website",
            "address",
            "is_active",
            "is_approved",
            "created_at",
            "updated_at",
            "user",
            "user_info",
        ]
        read_only_fields = [
            "slug",
            "is_active",
            "is_approved",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        user_data = validated_data.pop("user_info")
        request_user = self.context["request"].user

        organisation = Organisation.objects.create(**validated_data)

        OrganisationUser.objects.create(
            user=request_user,
            organisation=organisation,
            **user_data
        )

        return organisation

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user_info", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if user_data:
            OrganisationUser.objects.filter(
                user=self.context["request"].user,
                organisation=instance,
            ).update(**user_data)

        return instance