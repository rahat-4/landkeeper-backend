from dj_rest_auth.serializers import LoginSerializer, JWTSerializer
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers
from apps.organisation.models import Organisation, OrganisationUser
from apps.subscription.models import UserSubscription, SubscriptionPlan

User = get_user_model()


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "profile_image",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "email",
            "phone",
            "password",
        ]

    def create(self, validated_data):
        with transaction.atomic():
            password = validated_data.pop("password")

            # 1. Create user
            user = User(**validated_data)
            user.set_password(password)
            user.save()

            # 2. Assign FREE subscription
            free_plan = SubscriptionPlan.objects.filter(name__iexact="free").first()
            if not free_plan:
                raise serializers.ValidationError("Free plan is not configured.")

            UserSubscription.objects.create(user=user, plan=free_plan, is_active=True)

            # 3. Create default organisation
            organisation = Organisation.objects.create(
                name=f"{user.first_name}'s Organisation",
                primary_mobile=user.phone or "",
            )

            # 4. Add user as OWNER in organisation
            OrganisationUser.objects.create(
                user=user,
                organisation=organisation,
            )

            return user


class CustomLoginSerializer(LoginSerializer):
    username = None
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, required=False)

    class Meta:
        model = User
        fields = [
            "alias",
            "email",
            "password",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "role",
            "phone",
            "profile_image",
            "city",
            "state",
            "country",
            "post_code",
            "address",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["alias", "created_at", "updated_at"]

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "This field is required."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.is_password_set = True
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        if password:
            instance.set_password(password)
            instance.is_password_set = True
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class UserProfileSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = [
            "email",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "phone",
            "profile_image",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["email", "is_active", "created_at", "updated_at"]


class CustomJWTSerializer(JWTSerializer):
    user = UserSerializer(read_only=True)
