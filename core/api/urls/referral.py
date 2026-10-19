from django.urls import path

from ..views.referral import JoinReferralView, CouponValidationView

urlpatterns = [
    path("/join", JoinReferralView.as_view(), name="join-referral"),
    path("/validate-coupon", CouponValidationView.as_view(), name="validate-coupon"),
]
