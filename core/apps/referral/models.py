# import uuid

# from django.core.exceptions import ValidationError
# from django.utils.translation import gettext_lazy as _
# from django.contrib.auth import get_user_model
# from django.db import models
# from django.utils import timezone

# from apps.organisation.models import Organisation
# from apps.referral.enums import (
#     AmbassadorStatusChoices,
#     ReferralStatusChoices,
#     CommissionStatusChoices,
# )
# from common.models import CreatedAtUpdatedAtBaseModel

# User = get_user_model()

# ELIGIBILITY_WINDOW_DAYS = 60
# ELIGIBILITY_REFERRAL_COUNT = 5
# COMMISSION_PERCENTAGE = 20
# REFERRED_MEMBER_DISCOUNT_PERCENTAGE = 20


# class AmbassadorProfile(CreatedAtUpdatedAtBaseModel):
#     user = models.OneToOneField(
#         User, on_delete=models.CASCADE, related_name="ambassador_profile"
#     )
#     referral_code = models.CharField(max_length=16, unique=True, editable=False)
#     status = models.CharField(
#         max_length=16,
#         choices=AmbassadorStatusChoices.choices,
#         default=AmbassadorStatusChoices.PENDING,
#     )
#     eligibility_deadline = models.DateTimeField(editable=False)
#     bank_account_name = models.CharField(max_length=128, blank=True, null=True)
#     bank_account_number = models.CharField(max_length=64, blank=True, null=True)
#     bank_sort_code = models.CharField(max_length=16, blank=True, null=True)
#     bank_name = models.CharField(max_length=128, blank=True, null=True)

#     class Meta:
#         verbose_name = _("Ambassador Profile")
#         verbose_name_plural = _("Ambassador Profiles")
#         ordering = ["-created_at"]

#     def __str__(self):
#         return f"{self.user.email} ({self.get_status_display()})"

#     @staticmethod
#     def generate_referral_code() -> str:
#         return uuid.uuid4().hex[:8].upper()

#     def save(self, *args, **kwargs):
#         if not self.pk:
#             if not self.referral_code:
#                 self.referral_code = self.generate_referral_code()
#             if not self.eligibility_deadline:
#                 self.eligibility_deadline = timezone.now() + timezone.timedelta(
#                     days=ELIGIBILITY_WINDOW_DAYS
#                 )
#         super().save(*args, **kwargs)

#     def qualifying_referral_count(self) -> int:
#         return self.referrals.filter(
#             status=ReferralStatusChoices.SIGNED_UP,
#             created_at__lte=self.eligibility_deadline,
#         ).count()

#     def check_and_update_eligibility(self):
#         if self.status != AmbassadorStatusChoices.PENDING:
#             return
#         if self.qualifying_referral_count() >= ELIGIBILITY_REFERRAL_COUNT:
#             self.status = AmbassadorStatusChoices.ELIGIBLE
#             self.save(update_fields=["status", "updated_at"])
#         elif timezone.now() > self.eligibility_deadline:
#             self.status = AmbassadorStatusChoices.EXPIRED
#             self.save(update_fields=["status", "updated_at"])


# class Referral(CreatedAtUpdatedAtBaseModel):
#     ambassador = models.ForeignKey(
#         AmbassadorProfile, on_delete=models.PROTECT, related_name="referrals"
#     )
#     invited_email = models.EmailField()
#     invite_token = models.CharField(max_length=64, unique=True, editable=False)
#     referred_user = models.ForeignKey(
#         User,
#         on_delete=models.CASCADE,
#         related_name="referrals_made",
#         null=True,
#         blank=True,
#     )
#     referred_organisation = models.OneToOneField(
#         Organisation,
#         on_delete=models.CASCADE,
#         related_name="referral",
#         null=True,
#         blank=True,
#     )

#     status = models.CharField(
#         max_length=16,
#         choices=ReferralStatusChoices.choices,
#         default=ReferralStatusChoices.INVITED,
#     )
#     discount_percentage = models.PositiveSmallIntegerField(
#         default=REFERRED_MEMBER_DISCOUNT_PERCENTAGE
#     )
#     registered_at = models.DateTimeField(null=True, blank=True)

#     class Meta:
#         verbose_name = _("Referral")
#         verbose_name_plural = _("Referrals")
#         ordering = ["-created_at"]
#         constraints = [
#             models.UniqueConstraint(
#                 fields=["ambassador", "invited_email"],
#                 name="unique_ambassador_invited_email",
#             )
#         ]

#     def __str__(self):
#         target = (
#             self.referred_organisation.name
#             if self.referred_organisation
#             else self.invited_email
#         )
#         return f"{target} <- {self.ambassador.user.email}"

#     def clean(self):
#         if self.ambassador_id and self.invited_email == self.ambassador.user.email:
#             raise ValidationError(_("An ambassador cannot refer themselves."))

#     @staticmethod
#     def generate_invite_token() -> str:
#         return uuid.uuid4().hex

#     def save(self, *args, **kwargs):
#         if not self.pk and not self.invite_token:
#             self.invite_token = self.generate_invite_token()
#         super().save(*args, **kwargs)

#     def complete_registration(self, user, organisation):
#         self.referred_user = user
#         self.referred_organisation = organisation
#         self.status = ReferralStatusChoices.SIGNED_UP
#         self.registered_at = timezone.now()
#         self.save(
#             update_fields=[
#                 "referred_user",
#                 "referred_organisation",
#                 "status",
#                 "registered_at",
#                 "updated_at",
#             ]
#         )
#         self.ambassador.check_and_update_eligibility()


# class ReferralCommission(CreatedAtUpdatedAtBaseModel):
#     referral = models.ForeignKey(
#         Referral, on_delete=models.PROTECT, related_name="commissions"
#     )
#     # subscription = models.ForeignKey(
#     #     "subscription.UserSubscription",
#     #     on_delete=models.PROTECT,
#     #     related_name="referral_commissions",
#     # )
#     billing_period_start = models.DateField()
#     billing_period_end = models.DateField()
#     commission_percentage = models.PositiveSmallIntegerField(
#         default=COMMISSION_PERCENTAGE
#     )
#     commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
#     status = models.CharField(
#         max_length=16,
#         choices=CommissionStatusChoices.choices,
#         default=CommissionStatusChoices.PENDING,
#     )

#     def __str__(self):
#         return (
#             f"{self.referral} - {self.commission_amount} ({self.get_status_display()})"
#         )

#     class Meta:
#         verbose_name = _("Referral Commission")
#         verbose_name_plural = _("Referral Commissions")
#         ordering = ["-created_at"]
