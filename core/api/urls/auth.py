from allauth.headless.account.views import ResetPasswordView
from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from api.views.auth import (
    GoogleLoginView,
    CustomLoginView,
    SetForgotPasswordView,
    ForgotPasswordView,
    ChangePasswordView,
)

urlpatterns = [
    path("login/", CustomLoginView.as_view(), name="login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("social/google/", GoogleLoginView.as_view(), name="google-login"),
    path("password/forgot/", ForgotPasswordView.as_view(), name="forgot_password"),
    path("password/reset/<uidb64>/<token>/", SetForgotPasswordView.as_view(), name="reset_password"),
    path("password/change/", ChangePasswordView.as_view(), name="change_password"),
]