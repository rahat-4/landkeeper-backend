from rest_framework.exceptions import NotFound
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView
)
from rest_framework.permissions import IsAuthenticated
from apps.organisation.models import Organisation
from api.serializers.organisation import OrganisationSerializer


class OrganisationOnboardingListCreateAPIView(ListCreateAPIView):
    serializer_class = OrganisationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Organisation.objects.filter(
            organisation_users__user=self.request.user,
            is_active=True,
        )


class OrganisationOnboardingDetailAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = OrganisationSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"

    def get_object(self):
        try:
            return Organisation.objects.get(
                slug=self.kwargs["slug"],
                organisation_users__user=self.request.user,
                is_active=True,
            )
        except Organisation.DoesNotExist:
            raise NotFound("Organisation not found.")

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])