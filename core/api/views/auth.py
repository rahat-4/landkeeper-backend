from datetime import timedelta
from django.utils import timezone
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from dj_rest_auth.registration.views import SocialLoginView
from dj_rest_auth.views import LoginView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from api.utils import send_password_reset_email, send_verification_email
from apps.authentication.models import User, EmailVerification
from urllib.parse import urlencode
from django.http import HttpResponseRedirect
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from apps.authentication.signals import create_default_organisation
from ..serializers.auth import (
    UserRegistrationSerializer,
    UserProfileSerializer,
    EmailVerifySerializer
)

class AccountRegistrationView(CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return User.objects.all()

    def perform_create(self, serializer):
        user = serializer.save()
        create_default_organisation(user)

class EmailVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"detail": "Email verified successfully. You can now log in."},
            status=status.HTTP_200_OK
        )

class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response(
                {"detail": "Email is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(email=email, is_active=False)
        except User.DoesNotExist:
            return Response(
                {"detail": "No unverified user found with this email."},
                status=status.HTTP_404_NOT_FOUND
            )

        code = EmailVerification.make_code()

        try:
            verification = EmailVerification.objects.get(user=user)
            verification.code = code
            verification.is_verified = False
            verification.expires_at = timezone.now() + timedelta(minutes=2)
            verification.save()
        except EmailVerification.DoesNotExist:
            EmailVerification.objects.create(
                user=user,
                code=code,
            )
        send_verification_email(user, code)
        return Response(
            {"detail": "Verification code resent."},
            status=status.HTTP_200_OK
        )

class CustomLoginView(LoginView):
    permission_classes = [AllowAny]


class GoogleLoginView(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = "http://localhost:8002/auth/social/google/"
    client_class = OAuth2Client


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")

        # Check if email field is provided
        if not email:
            return Response(
                {"email": "This field is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Check if email format is valid
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError

        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"email": "Enter a valid email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user exists with this email
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"email": "No account found with this email address."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if the user account is active
        if not user.is_active:
            return Response(
                {"email": "This account is inactive. Please contact support."},
                status=status.HTTP_403_FORBIDDEN,
            )

        send_password_reset_email(user)

        return Response(
            {"detail": "Password reset link has been sent to your email."},
            status=status.HTTP_200_OK,
        )


class SetForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            params = urlencode({"error": "invalid_link"})
            return HttpResponseRedirect(
                f"{settings.FRONTEND_URL}/auth/password-error?{params}"
            )

        if not default_token_generator.check_token(user, token):
            params = urlencode({"error": "expired_or_invalid"})
            return HttpResponseRedirect(
                f"{settings.FRONTEND_URL}/auth/password-error?{params}"
            )

        params = urlencode({"uid": uidb64, "token": token})
        return HttpResponseRedirect(
            f"{settings.FRONTEND_URL}/auth/set-password?{params}"
        )

    def post(self, request, uidb64, token):
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not new_password or not confirm_password:
            return Response(
                {"detail": "Both password fields are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response(
                {"detail": "Passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {"detail": "Invalid reset link."}, status=status.HTTP_400_BAD_REQUEST
            )

        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Reset link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()
        return Response(
            {"detail": "Password has been reset successfully."},
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        old_password = request.data.get("old_password")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not all([old_password, new_password, confirm_password]):
            return Response(
                {"detail": "All fields are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.user.check_password(old_password):
            return Response(
                {"detail": "Old password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response(
                {"detail": "Passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if old_password == new_password:
            return Response(
                {"detail": "New password must be different from old password."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(new_password)
        request.user.save()
        return Response(
            {"detail": "Password changed successfully."}, status=status.HTTP_200_OK
        )

class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh_token")

            if not refresh_token:
                return Response(
                    {"error": "Refresh token is required."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response(
                {"detail": "Logged out successfully."},
                status=status.HTTP_200_OK,
            )

        except TokenError as e:
            return Response(
                {"error": "Invalid or expired token."},
                status=status.HTTP_400_BAD_REQUEST
            )

class UserProfileView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_object(self):
        return self.request.user
