from datetime import timedelta
import requests
import logging
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from dj_rest_auth.registration.views import SocialLoginView
from dj_rest_auth.views import LoginView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.exceptions import TokenError
from api.utils import (
    send_password_reset_email,
    send_verification_email,
    send_invite_email,
    send_tenant_invite_email,
)
from apps.authentication.models import User, EmailVerification, InviteUser
from urllib.parse import urlencode
from django.http import HttpResponseRedirect
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.generics import CreateAPIView, RetrieveUpdateAPIView, ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from apps.organisation.enums import OrganisationRoleChoices
from apps.organisation.models import OrganisationUser, Organisation
from apps.organisation.utils import get_request_organisation
from apps.property.models import Tenant
from apps.referral.models import Referral
from common.permission import IsLandlord, IsSuperAdmin
from api.serializers.organisation import OrganisationUserSerializer
from ..serializers.auth import (
    UserRegistrationSerializer,
    UserProfileSerializer,
    TenantProfileSerializer,
    EmailVerifySerializer,
    InviteUserSerializer,
    AcceptInviteSerializer,
    TenantAcceptInviteSerializer,
    ReferralRegistrationSerializer,
)
from django.shortcuts import get_object_or_404

logger = logging.getLogger(__name__)


class AccountRegistrationView(CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return User.objects.all()


class JoinReferralProgramView(CreateAPIView):
    serializer_class = ReferralRegistrationSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        referral = user.referral_profile

        return Response(
            {
                "message": "Referral account created.",
                "email": user.email,
                "coupon_code": referral.coupon_code,
                "affiliate_id": referral.affiliate_id,
            },
            status=status.HTTP_201_CREATED,
        )


class EmailVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"detail": "Email verified successfully. You can now log in."},
            status=status.HTTP_200_OK,
        )


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response(
                {"detail": "Email is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.get(email=email, is_active=False)
        except User.DoesNotExist:
            return Response(
                {"detail": "No unverified user found with this email."},
                status=status.HTTP_404_NOT_FOUND,
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
            {"detail": "Verification code resent."}, status=status.HTTP_200_OK
        )


def get_tokens_for_tenant(tenant):
    refresh = RefreshToken()

    user_id = tenant.pk
    if not isinstance(user_id, int):
        user_id = str(user_id)
    refresh[api_settings.USER_ID_CLAIM] = user_id

    refresh["user_type"] = "tenant"
    refresh["organisation_id"] = tenant.property.organisation_id
    return refresh


class CustomLoginView(LoginView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        email = (request.data.get("email") or "").lower().strip()
        password = request.data.get("password")

        if not email or not password:
            return Response(
                {"detail": "Email and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # TENANT LOGIN
        tenant = Tenant.objects.filter(email=email).first()
        if tenant is not None:
            if not tenant.check_password(password):
                return Response(
                    {"detail": "Invalid credentials."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not tenant.is_active:
                return Response(
                    {"detail": "This tenant account is inactive."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            refresh = get_tokens_for_tenant(tenant)

            return Response(
                {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "user_type": "tenant",
                    "tenant": {
                        "id": tenant.id,
                        "email": tenant.email,
                        "full_name": tenant.get_full_name(),
                        "organisation_id": tenant.organisation_id,
                        "property_id": tenant.property_id,
                    },
                },
                status=status.HTTP_200_OK,
            )
        # DEFAULT USER LOGIN
        return super().post(request, *args, **kwargs)


def get_user_type_label(user):
    if user.is_superuser:
        return "SUPER_ADMIN"

    organisation_user = user.organisation_users.first()
    if organisation_user:
        return organisation_user.role
    return "LANDLORD"


class GoogleLoginView(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    callback_url = settings.GOOGLE_CALLBACK_URL
    client_class = OAuth2Client

    def post(self, request, *args, **kwargs):
        self.request = request

        data = (
            request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        )

        access_token = data.get("access_token")

        # Support either a Google access token or authorization code.
        if not access_token:
            code = data.get("code")

            if not code:
                return Response(
                    {"detail": "access_token or code is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                access_token = self._exchange_code_for_access_token(code)
            except Exception:
                logger.exception("Google authorization-code exchange failed.")
                return Response(
                    {"detail": "Unable to authenticate with Google."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            data["access_token"] = access_token
            data.pop("code", None)

        email = self._get_google_email(access_token)

        if email:
            email = email.lower().strip()

            tenant = Tenant.objects.filter(email__iexact=email).first()

            if tenant is not None:
                return self._tenant_login_response(tenant)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        self.serializer = serializer
        self.login()

        user = self.user

        self._create_default_organisation(user)

        return self.get_response()

    def _create_default_organisation(self, user):
        with transaction.atomic():
            locked_user = User.objects.select_for_update().get(pk=user.pk)

            if locked_user.get_organisation():
                return

            organisation = Organisation.objects.create(
                name=(
                    f"{locked_user.first_name or locked_user.email}" "'s Organisation"
                )
            )

            OrganisationUser.objects.create(
                user=locked_user,
                organisation=organisation,
            )

    def _exchange_code_for_access_token(self, code):
        adapter = self.adapter_class(self.request)
        provider = adapter.get_provider()
        app = provider.get_app(self.request)

        client = self.client_class(
            self.request,
            app.client_id,
            app.secret,
            adapter.access_token_method,
            adapter.access_token_url,
            self.callback_url,
            scope_delimiter=adapter.scope_delimiter,
            headers=adapter.headers,
            basic_auth=adapter.basic_auth,
        )

        token = client.get_access_token(code)
        return token["access_token"]

    def _get_google_email(self, access_token):
        try:
            response = requests.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=5,
            )
            response.raise_for_status()

            google_user = response.json()

            if not google_user.get("email_verified"):
                return None

            return google_user.get("email")

        except requests.RequestException:
            logger.warning("Could not retrieve verified Google user information.")
            return None

    def get_response(self):
        response = super().get_response()
        response.data["user"]["user_type"] = get_user_type_label(self.user)
        return response

    def _tenant_login_response(self, tenant):
        if not tenant.is_active:
            return Response(
                {"detail": "This tenant account is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = get_tokens_for_tenant(tenant)

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "tenant": {
                    "id": tenant.id,
                    "email": tenant.email,
                    "full_name": tenant.get_full_name(),
                    "organisation_id": tenant.organisation_id,
                    "organisation_name": tenant.organisation.name,
                    "property_id": tenant.property_id,
                    "property_name": tenant.property.property_name,
                    "user_type": "tenant",
                },
            },
            status=status.HTTP_200_OK,
        )


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response(
                {"email": "This field is required."}, status=status.HTTP_400_BAD_REQUEST
            )

        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError

        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"email": "Enter a valid email address."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email=email).first()
        if not user:
            user = Tenant.objects.filter(email=email).first()

        if not user:
            return Response(
                {"email": "No account found with this email address."},
                status=status.HTTP_404_NOT_FOUND,
            )

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

    def get_user_or_tenant(self, uid):
        try:
            return User.objects.get(pk=uid)
        except User.DoesNotExist:
            return Tenant.objects.get(pk=uid)

    def get(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = self.get_user_or_tenant(uid)
        except (
            TypeError,
            ValueError,
            OverflowError,
            User.DoesNotExist,
            Tenant.DoesNotExist,
        ):
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
            user = self.get_user_or_tenant(uid)
        except (
            TypeError,
            ValueError,
            OverflowError,
            User.DoesNotExist,
            Tenant.DoesNotExist,
        ):
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


class UpdatePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not new_password or not confirm_password:
            return Response(
                {"detail": "New password and confirm password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response(
                {"detail": "Passwords do not match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_has_password = request.user.has_usable_password()

        if user_has_password:
            old_password = request.data.get("old_password")
            if not old_password:
                return Response(
                    {"detail": "Old password is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not request.user.check_password(old_password):
                return Response(
                    {"detail": "Old password is incorrect."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if old_password == new_password:
                return Response(
                    {"detail": "New password must be different from old password."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        request.user.set_password(new_password)
        request.user.save()

        detail = (
            "Password changed successfully."
            if user_has_password
            else "Password set successfully. You can now log in with your email and password."
        )
        return Response({"detail": detail}, status=status.HTTP_200_OK)


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh_token")

            if not refresh_token:
                return Response(
                    {"error": "Refresh token is required."},
                    status=status.HTTP_400_BAD_REQUEST,
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
                status=status.HTTP_400_BAD_REQUEST,
            )


class UserProfileView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if isinstance(self.request.user, Tenant):
            return TenantProfileSerializer
        return UserProfileSerializer

    def get_object(self):
        return self.request.user


class SendInviteView(APIView):
    permission_classes = [IsAuthenticated, IsLandlord]

    def post(self, request):
        serializer = InviteUserSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        if email.lower() == request.user.email.lower():
            return Response(
                {"detail": "You cannot invite yourself."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        organisation = request.user.get_organisation()
        if not organisation:
            return Response(
                {"detail": "You are not part of any organisation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invite, created = InviteUser.objects.get_or_create(
            email=email,
            defaults={
                "role": serializer.validated_data.get("role"),
                "message": serializer.validated_data.get("message"),
                "organisation": organisation,
                "created_by": request.user,
            },
        )
        if not created:
            invite.role = serializer.validated_data.get("role", invite.role)
            invite.message = serializer.validated_data.get("message", invite.message)
            invite.updated_by = request.user
            invite.save()

        send_invite_email(
            invite=invite,
            organisation=organisation,
            inviter_name=request.user.get_full_name() or request.user.email,
        )

        return Response(
            InviteUserSerializer(invite).data, status=status.HTTP_201_CREATED
        )


class ResendInviteView(APIView):
    permission_classes = [IsAuthenticated, IsLandlord]

    def post(self, request, alias):
        organisation = request.user.get_organisation()
        if not organisation:
            return Response(
                {"detail": "You are not part of any organisation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invite = get_object_or_404(InviteUser, alias=alias, organisation=organisation)

        send_invite_email(
            invite=invite,
            organisation=organisation,
            inviter_name=request.user.get_full_name() or request.user.email,
        )

        return Response(
            {"detail": "Invite resent successfully."},
            status=status.HTTP_200_OK,
        )


class DeleteInviteView(APIView):
    permission_classes = [IsAuthenticated, IsLandlord]

    def delete(self, request, alias):
        organisation = request.user.get_organisation()
        if not organisation:
            return Response(
                {"detail": "You are not part of any organisation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        invite = get_object_or_404(InviteUser, alias=alias, organisation=organisation)
        invite.delete()
        return Response(
            {"detail": "Invite deleted successfully."},
            status=status.HTTP_200_OK,
        )


class AcceptInviteView(APIView):
    permission_classes = []

    def post(self, request, alias):
        invite = get_object_or_404(InviteUser, alias=alias)

        serializer = AcceptInviteSerializer(
            data=request.data,
            context={"invite": invite},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        organisation = user.get_organisation()

        return Response(
            {
                "message": "Account created successfully",
                "organisation": organisation.name if organisation else None,
            },
            status=status.HTTP_201_CREATED,
        )


class TenantSendInviteView(APIView):
    permission_classes = [IsSuperAdmin | IsLandlord]

    def post(self, request, tenant_alias):
        user = request.user

        organisation = get_request_organisation(request)
        tenant = get_object_or_404(
            Tenant, alias=tenant_alias, organisation=organisation
        )

        if not tenant.email:
            return Response({"detail": "Tenant has no email address."}, status=400)

        send_tenant_invite_email(
            tenant=tenant,
            organisation=organisation,
            inviter_name=user.get_full_name() or user.email,
        )
        return Response({"detail": "Invitation sent."})


class TenantAcceptInviteView(APIView):
    permission_classes = []

    def post(self, request, tenant_alias):
        tenant = get_object_or_404(Tenant, alias=tenant_alias)

        if tenant.has_usable_password():
            return Response(
                {"detail": "Invite already accepted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not tenant.email:
            return Response(
                {"detail": "Tenant has no email on file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TenantAcceptInviteSerializer(
            data=request.data,
            context={"tenant": tenant},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response(
            {
                "message": "Account created successfully. You can now log in.",
            },
            status=status.HTTP_201_CREATED,
        )


class OrganisationUserListAPIView(ListAPIView):
    serializer_class = OrganisationUserSerializer
    pagination_class = None
    search_fields = ["user__email", "user__first_name", "user__last_name"]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            return OrganisationUser.objects.none()

        role = self.request.query_params.get("role")
        if not role:
            raise ValidationError({"role": "This query parameter is required."})

        valid_roles = OrganisationRoleChoices.values
        if role not in valid_roles:
            raise ValidationError(
                {"role": f"Invalid role. Must be one of {valid_roles}."}
            )

        return OrganisationUser.objects.filter(
            organisation=organisation, role=role
        ).select_related("user")
