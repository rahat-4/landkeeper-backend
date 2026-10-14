from django.urls import path

from ..views.referral import JoinReferralView

urlpatterns = [
    path("/join", JoinReferralView.as_view(), name="join-referral"),
]
