# from django.contrib.auth import get_user_model
# from django.contrib.auth.password_validation import validate_password
# from django.db import transaction
# from django.utils import timezone
# import re
# from apps.referral.tasks import send_referral_invite_email_task
# from rest_framework import serializers

# from apps.organisation.models import Organisation, OrganisationUser
# from apps.organisation.enums import OrganisationRoleChoices
# from apps.referral.models import AmbassadorProfile, Referral, ReferralCommission
# from apps.referral.enums import ReferralStatusChoices

# User = get_user_model()


# class AmbassadorRegistrationSerializer(serializers.ModelSerializer):
#     UK_SORT_CODE_RE = re.compile(r"^\d{2}-?\d{2}-?\d{2}$")
#     UK_ACCOUNT_NUMBER_RE = re.compile(r"^\d{6,8}$")
#     BANK_FIELDS = (
#         "bank_account_name",
#         "bank_name",
#         "bank_account_number",
#         "bank_sort_code",
#     )

#     first_name = serializers.CharField(max_length=64, required=False, write_only=True)
#     last_name = serializers.CharField(max_length=64, required=False, write_only=True)
#     phone = serializers.CharField(
#         max_length=24, required=False, allow_blank=True, write_only=True
#     )
#     bank_account_number_masked = serializers.SerializerMethodField()

#     class Meta:
#         model = AmbassadorProfile
#         fields = (
#             "first_name",
#             "last_name",
#             "phone",
#             "bank_account_name",
#             "bank_name",
#             "bank_account_number",
#             "bank_sort_code",
#             "bank_account_number_masked",
#             "referral_code",
#             "status",
#             "eligibility_deadline",
#             "created_at",
#         )
#         read_only_fields = (
#             "referral_code",
#             "status",
#             "eligibility_deadline",
#             "created_at",
#         )
#         extra_kwargs = {"bank_account_number": {"write_only": True}}

#     def validate_bank_account_number(self, value):
#         if not value:
#             return value
#         cleaned = value.replace(" ", "")
#         if not self.UK_ACCOUNT_NUMBER_RE.match(cleaned):
#             raise serializers.ValidationError(
#                 "Enter a valid account number (6-8 digits)."
#             )
#         return cleaned

#     def validate_bank_sort_code(self, value):
#         if not value:
#             return value
#         cleaned = value.replace(" ", "")
#         if not self.UK_SORT_CODE_RE.match(cleaned):
#             raise serializers.ValidationError("Enter a valid sort code, e.g. 12-34-56.")
#         digits = cleaned.replace("-", "")
#         return f"{digits[0:2]}-{digits[2:4]}-{digits[4:6]}"

#     def validate_bank_account_name(self, value):
#         if not value:
#             return value
#         value = value.strip()
#         if len(value) < 2:
#             raise serializers.ValidationError("Enter the account holder's name.")
#         return value

#     def validate_bank_name(self, value):
#         return value.strip() if value else value

#     def validate(self, attrs):
#         provided = [f for f in self.BANK_FIELDS if attrs.get(f)]
#         if provided and len(provided) != len(self.BANK_FIELDS):
#             missing = [f for f in self.BANK_FIELDS if f not in provided]
#             raise serializers.ValidationError(
#                 {
#                     "detail": "Provide all bank details together, or leave them all blank for now.",
#                     "missing_fields": missing,
#                 }
#             )
#         return attrs

#     def get_bank_account_number_masked(self, obj):
#         if not obj.bank_account_number:
#             return None
#         return f"****{obj.bank_account_number[-4:]}"

#     @transaction.atomic
#     def create(self, validated_data):
#         user = self.context["request"].user

#         if AmbassadorProfile.objects.filter(user=user).exists():
#             raise serializers.ValidationError(
#                 {"detail": "This user is already registered as an ambassador."}
#             )

#         user_fields_changed = []
#         for field in ("first_name", "last_name", "phone"):
#             value = validated_data.pop(field, None)
#             if value:
#                 setattr(user, field, value)
#                 user_fields_changed.append(field)
#         if user_fields_changed:
#             user.save(update_fields=user_fields_changed)

#         return AmbassadorProfile.objects.create(user=user, **validated_data)


# class AmbassadorProfileSerializer(serializers.ModelSerializer):
#     """Read-only view of an ambassador's own dashboard summary."""

#     bank_account_number_masked = serializers.SerializerMethodField()
#     qualifying_referral_count = serializers.SerializerMethodField()
#     referrals_remaining = serializers.SerializerMethodField()

#     class Meta:
#         model = AmbassadorProfile
#         fields = (
#             "referral_code",
#             "status",
#             "eligibility_deadline",
#             "bank_account_name",
#             "bank_name",
#             "bank_account_number_masked",
#             "qualifying_referral_count",
#             "referrals_remaining",
#             "created_at",
#         )
#         read_only_fields = fields

#     def get_bank_account_number_masked(self, obj):
#         if not obj.bank_account_number:
#             return None
#         return f"****{obj.bank_account_number[-4:]}"

#     def get_qualifying_referral_count(self, obj):
#         return obj.qualifying_referral_count()

#     def get_referrals_remaining(self, obj):
#         from apps.referral.models import ELIGIBILITY_REFERRAL_COUNT

#         remaining = ELIGIBILITY_REFERRAL_COUNT - obj.qualifying_referral_count()
#         return max(remaining, 0)


# # Referral — sending an invite
# class ReferralInviteCreateSerializer(serializers.ModelSerializer):

#     class Meta:
#         model = Referral
#         fields = ("invited_email", "invite_token", "status", "created_at")
#         read_only_fields = ("invite_token", "status", "created_at")

#     def validate_invited_email(self, value):
#         value = value.strip().lower()
#         ambassador = self.context["ambassador"]

#         if value == ambassador.user.email.lower():
#             raise serializers.ValidationError("You cannot refer yourself.")

#         if User.objects.filter(email__iexact=value).exists():
#             raise serializers.ValidationError(
#                 "This email is already registered on the platform."
#             )

#         existing = Referral.objects.filter(
#             ambassador=ambassador, invited_email__iexact=value
#         ).first()
#         if existing and existing.status == ReferralStatusChoices.SIGNED_UP:
#             raise serializers.ValidationError(
#                 "This person has already registered from your invite."
#             )

#         return value

#     @transaction.atomic
#     def create(self, validated_data):
#         ambassador = self.context["ambassador"]
#         invited_email = validated_data["invited_email"]

#         existing = Referral.objects.filter(
#             ambassador=ambassador,
#             invited_email__iexact=invited_email,
#             status=ReferralStatusChoices.INVITED,
#         ).first()

#         if existing:
#             existing.invite_token = Referral.generate_invite_token()
#             existing.save(update_fields=["invite_token", "updated_at"])
#             referral = existing
#         else:
#             referral = Referral.objects.create(
#                 ambassador=ambassador, invited_email=invited_email
#             )

#         transaction.on_commit(
#             lambda: send_referral_invite_email_task.delay(referral.id)
#         )
#         return referral


# # Referral accepting an invite / registering
# class ReferralAcceptSerializer(serializers.Serializer):
#     invite_token = serializers.CharField(write_only=True)
#     first_name = serializers.CharField(max_length=64)
#     middle_name = serializers.CharField(
#         max_length=64,
#         required=False,
#         allow_blank=True,
#         allow_null=True,
#     )
#     last_name = serializers.CharField(max_length=64)
#     password = serializers.CharField(write_only=True)
#     organisation_name = serializers.CharField(
#         max_length=128, required=False, allow_blank=True
#     )

#     def validate_invite_token(self, value):
#         try:
#             referral = Referral.objects.select_related("ambassador__user").get(
#                 invite_token=value, status=ReferralStatusChoices.INVITED
#             )
#         except Referral.DoesNotExist:
#             raise serializers.ValidationError(
#                 "This invite link is invalid or has already been used."
#             )
#         self.context["referral"] = referral
#         return value

#     def validate_password(self, value):
#         validate_password(value)
#         return value

#     @transaction.atomic
#     def create(self, validated_data):
#         referral = self.context["referral"]
#         first_name = validated_data["first_name"]
#         middle_name = validated_data["middle_name"]
#         last_name = validated_data["last_name"]

#         user = User.objects.create_user(
#             email=referral.invited_email,
#             first_name=first_name,
#             middle_name=validated_data.get("middle_name"),
#             last_name=last_name,
#             password=validated_data["password"],
#         )

#         org_name = (
#             validated_data.get("organisation_name")
#             or f"{first_name} {last_name}".strip()
#         )
#         organisation = Organisation.objects.create(name=org_name)

#         OrganisationUser.objects.create(
#             user=user,
#             organisation=organisation,
#             role=OrganisationRoleChoices.LANDLORD,
#         )

#         referral.complete_registration(user=user, organisation=organisation)
#         return referral

#     def to_representation(self, instance):
#         return {
#             "status": instance.status,
#             "referred_organisation": instance.referred_organisation.name,
#             "registered_at": instance.registered_at,
#         }


# class ReferralListSerializer(serializers.ModelSerializer):
#     referred_organisation_name = serializers.CharField(
#         source="referred_organisation.name", read_only=True, default=None
#     )

#     class Meta:
#         model = Referral
#         fields = (
#             "id",
#             "invited_email",
#             "status",
#             "discount_percentage",
#             "referred_organisation_name",
#             "registered_at",
#             "created_at",
#         )
#         read_only_fields = fields


# class ReferralCommissionSerializer(serializers.ModelSerializer):
#     referred_organisation_name = serializers.CharField(
#         source="referral.referred_organisation.name", read_only=True
#     )

#     class Meta:
#         model = ReferralCommission
#         fields = (
#             "id",
#             "referred_organisation_name",
#             "commission_percentage",
#             "status",
#             "created_at",
#         )
#         read_only_fields = fields
