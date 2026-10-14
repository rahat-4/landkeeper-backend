import math
import random

from dj_rest_auth.serializers import LoginSerializer, JWTSerializer
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework import status
from apps.authentication.models import EmailVerification, InviteUser
from apps.authentication.enums import NameTitleChoices
from apps.organisation.models import (
    Organisation,
    OrganisationUser,
    OrganisationSubscription,
)
from apps.property.models import Tenant
from apps.referral.models import Referral
from apps.referral.affonso import AffonsoAPI
from apps.referral.utils import get_coupon_code

from api.utils import send_verification_email

User = get_user_model()


class AffonsoRegistrationError(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "Failed to create the referral account."
    default_code = "affonso_error"


class AffiliateAlreadyExistsError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "An affiliate with this email already exists in the referral program."
    )
    default_code = "affiliate_already_exists"


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    is_referral = serializers.BooleanField(
        write_only=True, required=False, default=False
    )

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
            "is_referral",
        ]

    def validate_email(self, value):
        if (
            User.objects.filter(email=value).exists()
            or InviteUser.objects.filter(email=value).exists()
            or Tenant.objects.filter(email=value).exists()
        ):
            raise serializers.ValidationError("Email is already in use.")

        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        is_referral = validated_data.pop("is_referral", False)

        with transaction.atomic():
            user = User(**validated_data)
            user.set_password(password)
            user.is_active = False
            user.save()

            if is_referral:
                affonso_api = AffonsoAPI()

                try:
                    affiliate = affonso_api.create_affiliate(user)

                    coupon_code = get_coupon_code(user)
                    coupon = affonso_api.create_coupon(
                        affiliate_id=affiliate["id"],
                        code=coupon_code,
                    )

                except Exception as exc:
                    error_message = str(exc)

                    if (
                        "DUPLICATE_ERROR" in error_message
                        or "already exists in this program" in error_message
                    ):
                        raise AffiliateAlreadyExistsError() from exc

                    raise AffonsoRegistrationError() from exc

                Referral.objects.create(
                    user=user,
                    affiliate_id=affiliate["id"],
                    coupon_code=coupon.get("code", coupon_code),
                )

            else:
                organisation = Organisation.objects.create(
                    name=f"{user.first_name}'s Organisation"
                )

                OrganisationUser.objects.create(
                    user=user,
                    organisation=organisation,
                )

            code = EmailVerification.make_code()
            EmailVerification.objects.create(user=user, code=code)
            send_verification_email(user, code)

            return user


class EmailVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(max_length=6)

    def validate(self, data):
        try:
            user = User.objects.get(email=data["email"])
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid email.")

        try:
            verification = user.email_verification
        except EmailVerification.DoesNotExist:
            raise serializers.ValidationError("No verification code found.")

        if verification.is_verified:
            raise serializers.ValidationError("Email already verified.")

        if verification.is_expired():
            raise serializers.ValidationError(
                "Code has expired. Please request a new one."
            )

        if verification.code != data["code"]:
            raise serializers.ValidationError("Invalid code.")

        data["user"] = user
        data["verification"] = verification
        return data

    def save(self):
        user = self.validated_data["user"]
        verification = self.validated_data["verification"]

        verification.is_verified = True
        verification.save()

        user.is_active = True
        user.save()
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
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        if password:
            instance.set_password(password)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class UserProfileSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    is_password_available = serializers.SerializerMethodField()
    has_subscription = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()
    plan = serializers.SerializerMethodField()
    trial_days_left = serializers.SerializerMethodField()
    is_referral = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "email",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "current_address",
            "ni_number",
            "utr_number",
            "role",
            "phone",
            "profile_image",
            "is_active",
            "is_password_available",
            "has_subscription",
            "subscription_status",
            "plan",
            "trial_days_left",
            "is_referral",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["email", "role", "is_active", "created_at", "updated_at"]

    def get_role(self, obj):
        if obj.is_superuser:
            return "SUPER_ADMIN"

        else:
            return (
                obj.organisation_users.first().role
                if obj.organisation_users.exists()
                else None
            )

    def get_is_password_available(self, obj):
        return obj.has_usable_password()

    def get_subscription_status(self, obj):
        organisation = obj.get_organisation()

        if not organisation:
            return None

        subscription = getattr(organisation, "subscription", None)

        return subscription.status if subscription else None

    def get_has_subscription(self, obj):
        organisation = obj.get_organisation()

        if not organisation:
            return False

        return hasattr(organisation, "subscription")

    def get_plan(self, obj):
        organisation = obj.get_organisation()

        if not organisation:
            return None

        subscription = getattr(organisation, "subscription", None)

        return subscription.plan.plan_type if subscription else None

    def get_trial_days_left(self, obj):
        organisation = obj.get_organisation()

        if not organisation:
            return None

        subscription = getattr(organisation, "subscription", None)
        if not subscription:
            return None
        if (
            subscription.status != OrganisationSubscription.Status.TRIALING
            or not subscription.trial_end_date
        ):
            return None
        remaining = subscription.trial_end_date - timezone.now()
        if remaining.total_seconds() <= 0:
            return 0
        return math.ceil(remaining.total_seconds() / 86400)

    def get_is_referral(self, obj):
        return Referral.objects.filter(user=obj).exists()


class TenantProfileSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    is_password_available = serializers.SerializerMethodField()
    is_referral = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "email",
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "role",
            "phone",
            "avatar",
            "rent_amount",
            "is_active",
            "is_referral",
            "is_password_available",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "email",
            "role",
            "is_active",
            "created_at",
            "updated_at",
            "rent_amount",
        ]

    def get_role(self, obj):
        return "TENANT"

    def get_is_password_available(self, obj):
        return obj.has_usable_password()

    def get_is_referral(self, obj):
        return Referral.objects.filter(tenant=obj).exists()


class CustomJWTSerializer(JWTSerializer):
    user = UserSerializer(read_only=True)


class InviteUserSerializer(serializers.ModelSerializer):

    class Meta:
        model = InviteUser
        fields = [
            "alias",
            "email",
            "role",
            "message",
            "organisation",
        ]
        read_only_fields = [
            "alias",
            "created_at",
            "updated_at",
            "organisation",
        ]

    def validate_email(self, value):
        request = self.context.get("request")
        organisation = request.user.get_organisation() if request else None

        if not organisation:
            raise serializers.ValidationError("Organisation not found for the user.")

        if (
            User.objects.filter(email=value).exists()
            or InviteUser.objects.filter(email=value).exists()
            or Tenant.objects.filter(organisation=organisation, email=value).exists()
        ):
            raise serializers.ValidationError("Email is already in use.")

        return value


class AcceptInviteSerializer(serializers.Serializer):
    title = serializers.ChoiceField(choices=NameTitleChoices.choices)
    first_name = serializers.CharField(max_length=150)
    middle_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True
    )
    last_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=24, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError("Passwords do not match")

        invite = self.context.get("invite")
        if not invite:
            raise serializers.ValidationError("Invalid invite link")

        if User.objects.filter(email=invite.email).exists():
            raise serializers.ValidationError(
                "An account with this email already exists"
            )

        return data

    def create(self, validated_data):
        invite = self.context["invite"]

        with transaction.atomic():
            user = User.objects.create_user(
                title=validated_data["title"],
                first_name=validated_data["first_name"],
                middle_name=validated_data["middle_name"],
                last_name=validated_data["last_name"],
                email=invite.email,
                phone=validated_data["phone"],
                password=validated_data["password"],
            )

            OrganisationUser.objects.create(
                user=user,
                organisation=invite.organisation,
                role=invite.role,
            )

            invite.delete()

        return user


class TenantAcceptInviteSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError("Passwords do not match.")
        return data

    def save(self):
        tenant = self.context["tenant"]
        password = self.validated_data["new_password"]

        tenant.set_password(password)
        tenant.is_active = True
        tenant.is_password_set = True
        tenant.save(update_fields=["password", "is_active", "is_password_set"])

        return tenant
