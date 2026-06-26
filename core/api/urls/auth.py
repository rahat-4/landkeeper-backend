from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from api.views.auth import (
    AccountRegistrationView,
    GoogleLoginView,
    CustomLoginView,
    SetForgotPasswordView,
    ForgotPasswordView,
    ChangePasswordView,
    UserProfileView,
    EmailVerifyView,
    ResendVerificationView,
    LogoutAPIView,
)

urlpatterns = [
    path("/register", AccountRegistrationView.as_view(), name="register"),
    path("/verify-email", EmailVerifyView.as_view(), name="verify-email"),
    path("/resend-verify", ResendVerificationView.as_view(), name="resend-verify"),
    path("/login", CustomLoginView.as_view(), name="login"),
    path('/logout', LogoutAPIView.as_view(), name='logout'),
    path("/token/refresh", TokenRefreshView.as_view(), name="token_refresh"),
    path("/social/google", GoogleLoginView.as_view(), name="google-login"),
    path("/forgot-password", ForgotPasswordView.as_view(), name="forgot_password"),
    path(
        "/set-password/<uidb64>/<token>",
        SetForgotPasswordView.as_view(),
        name="set_forgot_password",
    ),
    path("/change-password", ChangePasswordView.as_view(), name="change_password"),
    path("/profile", UserProfileView.as_view(), name="user-profile"),
]
