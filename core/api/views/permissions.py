from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef
from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.response import Response
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    CreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.exceptions import NotFound, ValidationError

from apps.authentication.models import Permission
from apps.property.models import (
    Property,
    Mortgage,
)
from apps.organisation.utils import get_request_organisation


from ..serializers.permissions import (
    PermissionSerializer,
    BulkPropertyPermissionSerializer,
    AvailablePropertySerializer,
    AvailableMortgageSerializer,
)

from common.permission import (
    IsLandlord,
    IsAdmin,
    IsSuperAdmin,
)

User = get_user_model()


class PermissionListAPIView(CreateAPIView):
    permission_classes = [IsLandlord | IsAdmin]
    serializer_class = PermissionSerializer

    def get_organisation(self):
        organisation = get_request_organisation(self.request)

        if not organisation:
            raise NotFound("Organisation not found for the user.")

        return organisation

    def get_queryset(self):
        organisation = self.get_organisation()

        return Permission.objects.filter(organisation=organisation)

    def perform_create(self, serializer):
        organisation = self.get_organisation()

        serializer.save(organisation=organisation)


class PermissionDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [IsLandlord | IsAdmin]
    serializer_class = PermissionSerializer

    def get_organisation(self):
        organisation = get_request_organisation(self.request)

        if not organisation:
            raise NotFound("Organisation not found for the user.")

        return organisation

    def get_object(self):
        permission_alias = self.kwargs.get("permission_alias")
        organisation = self.get_organisation()

        return get_object_or_404(
            Permission,
            alias=permission_alias,
            organisation=organisation,
        )


class PropertyPermissionListAPIView(ListAPIView):
    permission_classes = [IsLandlord | IsAdmin]
    serializer_class = PermissionSerializer

    def get_organisation(self):
        organisation = get_request_organisation(self.request)

        if not organisation:
            raise NotFound("Organisation not found for the user.")

        return organisation

    def get_queryset(self):
        property_alias = self.kwargs.get("property_alias")
        organisation = self.get_organisation()

        property_obj = get_object_or_404(
            Property,
            alias=property_alias,
            organisation=organisation,
        )

        return Permission.objects.filter(
            property=property_obj,
            organisation=organisation,
        ).order_by("-created_at")


class MortgagePermissionListAPIView(ListAPIView):
    permission_classes = [IsLandlord | IsAdmin]
    serializer_class = PermissionSerializer

    def get_organisation(self):
        organisation = get_request_organisation(self.request)

        if not organisation:
            raise NotFound("Organisation not found for the user.")

        return organisation

    def get_queryset(self):
        mortgage_alias = self.kwargs.get("mortgage_alias")
        organisation = self.get_organisation()

        mortgage_obj = get_object_or_404(
            Mortgage,
            alias=mortgage_alias,
            organisation=organisation,
        )

        return Permission.objects.filter(
            mortgage=mortgage_obj,
            organisation=organisation,
        ).order_by("-created_at")


class BulkPropertyPermissionView(ListCreateAPIView):
    serializer_class = BulkPropertyPermissionSerializer
    permission_classes = [IsLandlord | IsSuperAdmin]

    def get_serializer_class(self):
        permission_status = self.request.query_params.get("permission_status")

        if permission_status == "not_added":
            return AvailablePropertySerializer

        return BulkPropertyPermissionSerializer

    def get_queryset(self):
        organisation = get_request_organisation(self.request)

        if not organisation:
            raise NotFound("Organisation not found for the user.")

        user_alias = self.kwargs.get("user_alias")

        user = get_object_or_404(
            User,
            alias=user_alias,
        )

        permission_status = self.request.query_params.get("permission_status")

        # ---------------------------------------------------------
        # Return properties that DON'T have permission for this user
        # ---------------------------------------------------------
        if permission_status == "not_added":
            existing_permissions = Permission.objects.filter(
                organisation=organisation,
                property=OuterRef("pk"),
            )

            return (
                Property.objects.filter(
                    organisation=organisation,
                )
                .annotate(has_permission=Exists(existing_permissions))
                .filter(has_permission=False)
                .order_by("-created_at")
            )

        # ---------------------------------------------------------
        # Default: return properties that already have permission
        # ---------------------------------------------------------
        return Permission.objects.filter(
            organisation=organisation,
            user=user,
            property__isnull=False,
        ).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        organisation = get_request_organisation(request)

        if not organisation:
            raise NotFound("Organisation not found for the user.")

        user = get_object_or_404(
            User,
            alias=self.kwargs.get("user_alias"),
        )

        property_aliases = serializer.validated_data["property"]

        properties = Property.objects.filter(
            alias__in=property_aliases,
            organisation=organisation,
        )

        if properties.count() != len(set(property_aliases)):
            raise ValidationError(
                {"property": ("One or more properties were not found.")}
            )

        can_view = serializer.validated_data["can_view"]
        can_edit = serializer.validated_data["can_edit"]

        with transaction.atomic():

            for property_obj in properties:

                # Find existing adviser assignment
                existing_permission = (
                    Permission.objects.filter(
                        organisation=organisation,
                        property=property_obj,
                    )
                    .exclude(user=user)
                    .first()
                )

                if existing_permission:
                    raise ValidationError(
                        {
                            "property": (
                                f"Property '{property_obj.property_name}' "
                                "is already assigned to another "
                                "user."
                            )
                        }
                    )

                # Create/update new adviser permission
                Permission.objects.update_or_create(
                    organisation=organisation,
                    user=user,
                    property=property_obj,
                    defaults={
                        "can_view": can_view,
                        "can_edit": can_edit,
                        "mortgage": None,
                    },
                )

        return Response(
            {
                "message": ("Property permissions updated successfully."),
                "user": user.alias,
                "properties_count": properties.count(),
            },
            status=status.HTTP_200_OK,
        )


class BulkMortgagePermissionView(ListCreateAPIView):
    serializer_class = BulkPropertyPermissionSerializer
    permission_classes = [IsLandlord | IsSuperAdmin]

    def get_serializer_class(self):
        permission_status = self.request.query_params.get("permission_status")

        if permission_status == "not_added":
            return AvailableMortgageSerializer

        return BulkPropertyPermissionSerializer

    def get_queryset(self):
        organisation = get_request_organisation(self.request)

        if not organisation:
            raise NotFound("Organisation not found for the user.")

        user_alias = self.kwargs.get("user_alias")

        user = get_object_or_404(
            User,
            alias=user_alias,
        )

        permission_status = self.request.query_params.get("permission_status")

        # ---------------------------------------------
        # Mortgages NOT assigned to this user
        # ---------------------------------------------
        if permission_status == "not_added":
            existing_permissions = Permission.objects.filter(
                organisation=organisation,
                mortgage=OuterRef("pk"),
            )

            return (
                Mortgage.objects.filter(
                    organisation=organisation,
                )
                .annotate(has_permission=Exists(existing_permissions))
                .filter(has_permission=False)
                .order_by("-created_at")
            )

        # ---------------------------------------------
        # Mortgages already assigned to this user
        # ---------------------------------------------
        return Permission.objects.filter(
            organisation=organisation,
            user=user,
            mortgage__isnull=False,
        ).order_by("-created_at")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        organisation = get_request_organisation(request)

        if not organisation:
            raise NotFound("Organisation not found for the user.")

        user = get_object_or_404(
            User,
            alias=self.kwargs.get("user_alias"),
        )

        mortgage_aliases = serializer.validated_data["mortgage"]

        mortgages = Mortgage.objects.filter(
            alias__in=mortgage_aliases,
            organisation=organisation,
        )

        if mortgages.count() != len(set(mortgage_aliases)):
            raise ValidationError(
                {"mortgage": ("One or more mortgages were not found.")}
            )

        can_view = serializer.validated_data["can_view"]
        can_edit = serializer.validated_data["can_edit"]

        with transaction.atomic():

            for mortgage_obj in mortgages:

                # Find existing adviser assignment
                existing_permission = (
                    Permission.objects.filter(
                        organisation=organisation,
                        mortgage=mortgage_obj,
                    )
                    .exclude(user=user)
                    .first()
                )

                if existing_permission:
                    raise ValidationError(
                        {
                            "mortgage": (
                                f"Mortgage '{mortgage_obj.mortgage_name}' "
                                "is already assigned to another "
                                "user."
                            )
                        }
                    )

                # Create/update new adviser permission
                Permission.objects.update_or_create(
                    organisation=organisation,
                    user=user,
                    mortgage=mortgage_obj,
                    defaults={
                        "can_view": can_view,
                        "can_edit": can_edit,
                        "property": None,
                    },
                )

        return Response(
            {
                "message": ("Mortgage permissions updated successfully."),
                "user": user.alias,
                "mortgages_count": mortgages.count(),
            },
            status=status.HTTP_200_OK,
        )
