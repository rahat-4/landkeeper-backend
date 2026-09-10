# from django.contrib import admin

# from apps.referral.models import AmbassadorProfile, Referral, ReferralCommission


# @admin.register(AmbassadorProfile)
# class AmbassadorProfileAdmin(admin.ModelAdmin):
#     list_display = (
#         "user",
#         "referral_code",
#         "status",
#         "eligibility_deadline",
#         "created_at",
#     )
#     list_filter = ("status",)
#     search_fields = ("user__email", "referral_code")
#     readonly_fields = (
#         "referral_code",
#         "eligibility_deadline",
#         "created_at",
#         "updated_at",
#     )


# @admin.register(Referral)
# class ReferralAdmin(admin.ModelAdmin):
#     list_display = (
#         "invited_email",
#         "ambassador",
#         "status",
#         "referred_organisation",
#         "registered_at",
#         "created_at",
#     )
#     list_filter = ("status",)
#     search_fields = ("invited_email", "ambassador__user__email", "invite_token")
#     readonly_fields = ("invite_token", "registered_at", "created_at", "updated_at")


# @admin.register(ReferralCommission)
# class ReferralCommissionAdmin(admin.ModelAdmin):
#     list_display = (
#         "referral",
#         "commission_percentage",
#         "commission_amount",
#         "status",
#         "created_at",
#     )
#     list_filter = ("status",)
#     search_fields = ("referral__invited_email",)
#     readonly_fields = ("created_at", "updated_at")
