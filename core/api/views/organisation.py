import stripe
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import (
    ListAPIView,
    RetrieveUpdateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.models import InviteUser
from apps.organisation.models import Organisation, OrganisationUser
from api.serializers.organisation import (
    OrganisationSerializer,
    OrganisationUserSerializer,
    OrganisationInviterUserSerializer,
)
from apps.organisation.stripe_connect import create_connect_account, create_account_link, logger
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


class StripeConnectOnboardingView(APIView):
    permission_classes = [IsLandlord]

    def post(self, request):
        organisation = request.user.get_organisation()
        if not organisation:
            return Response({"error": "No organisation found."}, status=status.HTTP_400_BAD_REQUEST)

        if not organisation.stripe_account_id:
            create_connect_account(organisation, email=request.user.email)

        try:
            account_link = create_account_link(organisation)
        except stripe.error.StripeError:
            logger.exception("Failed to create Stripe account link", extra={"organisation_id": organisation.id})
            return Response({"error": "Payment provider error. Please try again."}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"onboarding_url": account_link.url}, status=status.HTTP_200_OK)


class StripeConnectStatusView(APIView):
    permission_classes = [IsLandlord]

    def get(self, request):
        organisation = request.user.get_organisation()
        if not organisation:
            return Response({"error": "No organisation found."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "charges_enabled": organisation.stripe_charges_enabled,
            "payouts_enabled": organisation.stripe_payouts_enabled,
            "details_submitted": organisation.stripe_details_submitted,
        })