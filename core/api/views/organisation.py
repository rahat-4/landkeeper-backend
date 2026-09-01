import stripe
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import (
    ListAPIView,
    RetrieveUpdateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import InviteUser
from apps.organisation.models import Organisation, OrganisationUser
from api.serializers.organisation import (
    OrganisationSerializer,
    OrganisationUserSerializer,
    OrganisationInviterUserSerializer,
)
from apps.organisation.stripe_connect import (
    get_oauth_authorize_url,
    exchange_oauth_code,
    save_oauth_result,
    logger,
)

from common.permission import IsLandlord


class OrganisationListView(ListAPIView):
    serializer_class = OrganisationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Organisation.objects.filter(
            organisation_users__user=self.request.user,
            is_active=True,
        )


class OrganisationDetailView(RetrieveUpdateAPIView):
    serializer_class = OrganisationSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found.")
        return organisation


class OrganisationUserListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrganisationUserSerializer

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found.")
        return OrganisationUser.objects.filter(organisation=organisation).exclude(
            role="LANDLORD"
        )


class OrganisationInviteUserView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrganisationInviterUserSerializer

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found.")
        return InviteUser.objects.filter(organisation=organisation)


class OrganisationUserDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrganisationUserSerializer

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found.")
        return OrganisationUser.objects.filter(
            organisation=organisation,
            user__alias=self.kwargs["user_alias"],
        ).exclude(role="LANDLORD")

    def get_object(self):
        try:
            return self.get_queryset().get()
        except OrganisationUser.DoesNotExist:
            raise NotFound("Organisation user not found.")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["organisation"] = self.request.user.get_organisation()
        return context


class StripeConnectOAuthStartView(APIView):
    permission_classes = [IsLandlord]

    def get(self, request):
        organisation = request.user.get_organisation()
        if not organisation:
            return Response(
                {"error": "No organisation found."}, status=status.HTTP_400_BAD_REQUEST
            )

        authorize_url = get_oauth_authorize_url(organisation)
        return Response({"authorize_url": authorize_url}, status=status.HTTP_200_OK)


class StripeConnectOAuthCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        error = request.GET.get("error")

        if error:
            logger.warning(
                "Stripe OAuth denied by landlord",
                extra={"error": error, "state": state},
            )
            return Response(
                {"error": "Stripe connection was denied or cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not code or not state:
            return Response(
                {"error": "Missing code or state."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            organisation = Organisation.objects.get(id=state)
        except Organisation.DoesNotExist:
            return Response(
                {"error": "Invalid organisation."}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            oauth_response = exchange_oauth_code(code)
        except stripe.error.StripeError:
            logger.exception(
                "Stripe OAuth token exchange failed",
                extra={"organisation_id": organisation.id},
            )
            return Response(
                {"error": "Failed to connect Stripe account."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        save_oauth_result(organisation, oauth_response)

        return Response(
            {
                "connected": True,
                "stripe_account_id": organisation.stripe_account_id,
                "charges_enabled": organisation.stripe_charges_enabled,
            },
            status=status.HTTP_200_OK,
        )


class StripeConnectStatusView(APIView):
    permission_classes = [IsLandlord]

    def get(self, request):
        organisation = request.user.get_organisation()
        if not organisation:
            return Response(
                {"error": "No organisation found."}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {
                "charges_enabled": organisation.stripe_charges_enabled,
                "payouts_enabled": organisation.stripe_payouts_enabled,
                "details_submitted": organisation.stripe_details_submitted,
            }
        )
