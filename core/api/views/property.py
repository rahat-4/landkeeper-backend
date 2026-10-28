from django.contrib.auth.hashers import make_password
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organisation.models import OrganisationUser
from apps.organisation.enums import (
    OrganisationRoleChoices,
    OrganisationSubscriptionStatus,
)
from apps.property.models import (
    Property,
    Mortgage,
    Tenant,
    ComplianceAndCertification,
    UploadDocument,
    Finance,
    ComplianceShare,
)
from apps.organisation.utils import get_request_organisation

from common.permission import (
    IsLandlord,
    IsAdmin,
    CanAccessProperty,
    CanAccessMortgage,
    IsSuperAdmin,
)

from api.serializers.property import (
    PropertySerializer,
    MortgageSerializers,
    TenantSerializer,
    ComplianceAndCertificationSerializers,
    UploadDocumentSerializer,
    FinanceSerializer,
    PropertyOnboardingSerializer,
    ComplianceShareSerializer,
)


class PropertyListView(ListCreateAPIView):
    serializer_class = PropertySerializer
    permission_classes = [CanAccessProperty | IsSuperAdmin]
    filterset_fields = ["property_type", "status"]
    search_fields = ["property_name", "address"]

    def get_queryset(self):
        organisation = get_request_organisation(self.request)

        queryset = Property.objects.filter(organisation=organisation)

        if self.request.user.is_superuser:
            return queryset

        current_user = OrganisationUser.objects.filter(
            user=self.request.user,
            organisation=organisation,
        ).first()

        if current_user and current_user.role in [
            OrganisationRoleChoices.LANDLORD,
            OrganisationRoleChoices.ADMIN,
        ]:
            return queryset
        else:
            queryset = queryset.filter(
                property_permissions__user=self.request.user,
                property_permissions__organisation=organisation,
                property_permissions__can_view=True,
            ).distinct()

            return queryset

    def perform_create(self, serializer):
        organisation = get_request_organisation(self.request)

        if self.request.user.is_superuser:
            serializer.save(organisation=organisation)
            return

        subscription = getattr(organisation, "subscription", None)

        if not subscription:
            raise ValidationError({"subscription": "No active subscription found."})

        if subscription.status not in [
            OrganisationSubscriptionStatus.ACTIVE,
            OrganisationSubscriptionStatus.TRIALING,
        ]:
            raise ValidationError({"subscription": "Your subscription is not active."})

        max_properties = subscription.plan.max_properties

        current_property_count = Property.objects.filter(
            organisation=organisation
        ).count()

        if current_property_count >= max_properties:
            raise ValidationError(
                {
                    "property": (
                        f"Your {subscription.plan.name} plan allows "
                        f"a maximum of {max_properties} properties. "
                        "Please upgrade your plan to add more properties."
                    )
                }
            )

        serializer.save(organisation=organisation)


class PropertyDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = PropertySerializer
    permission_classes = [CanAccessProperty | IsSuperAdmin]

    def get_object(self):
        organisation = get_request_organisation(self.request)
        obj = get_object_or_404(
            Property,
            alias=self.kwargs["property_alias"],
            organisation=organisation,
        )
        self.check_object_permissions(self.request, obj)
        return obj


class MortgageListView(ListCreateAPIView):
    serializer_class = MortgageSerializers
    permission_classes = [CanAccessMortgage | IsSuperAdmin]
    search_fields = ["property__property_name", "lender_name"]

    def get_queryset(self):
        organisation = get_request_organisation(self.request)

        queryset = Mortgage.objects.filter(organisation=organisation)

        if self.request.user.is_superuser:
            return queryset

        # Mortgage advisers can only see permitted properties
        current_user = OrganisationUser.objects.filter(
            user=self.request.user,
            organisation=organisation,
        ).first()

        if current_user and current_user.role in [
            OrganisationRoleChoices.LANDLORD,
            OrganisationRoleChoices.ADMIN,
        ]:
            return queryset
        else:
            queryset = queryset.filter(
                mortgage_permissions__user=self.request.user,
                mortgage_permissions__organisation=organisation,
                mortgage_permissions__can_view=True,
            ).distinct()

            return queryset

    def perform_create(self, serializer):
        organisation = get_request_organisation(self.request)

        # The selected property must belong to the same organisation
        property_obj = serializer.validated_data.get("property")
        if property_obj and property_obj.organisation_id != organisation.id:
            raise ValidationError(
                {"property": "This property does not belong to this organisation."}
            )

        serializer.save(organisation=organisation)


class MortgageDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = MortgageSerializers
    permission_classes = [CanAccessMortgage | IsSuperAdmin]

    def get_object(self):
        organisation = get_request_organisation(self.request)
        obj = get_object_or_404(
            Mortgage,
            alias=self.kwargs["mortgage_alias"],
            organisation=organisation,
        )
        self.check_object_permissions(self.request, obj)
        return obj


class TenantListView(ListCreateAPIView):
    serializer_class = TenantSerializer
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]
    search_fields = [
        "property__property_name",
        "first_name",
        "last_name",
        "email",
        "phone",
    ]

    def get_queryset(self):
        organisation = get_request_organisation(self.request)
        return Tenant.objects.filter(organisation=organisation).order_by("-created_at")

    def perform_create(self, serializer):
        organisation = get_request_organisation(self.request)
        serializer.save(organisation=organisation, password=make_password(None))


class TenantDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = TenantSerializer
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]

    def get_object(self):
        organisation = get_request_organisation(self.request)
        return get_object_or_404(
            Tenant,
            alias=self.kwargs["tenant_alias"],
            organisation=organisation,
        )


class ComplianceAndCertificationListView(ListCreateAPIView):
    serializer_class = ComplianceAndCertificationSerializers
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]
    search_fields = ["property__property_name", "certificate_number"]

    def get_queryset(self):
        organisation = get_request_organisation(self.request)
        return ComplianceAndCertification.objects.filter(
            organisation=organisation
        ).order_by("-created_at")

    def perform_create(self, serializer):
        organisation = get_request_organisation(self.request)
        serializer.save(organisation=organisation)


class ComplianceAndCertificationDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = ComplianceAndCertificationSerializers
    permission_classes = [IsLandlord | IsAdmin | IsSuperAdmin]

    def get_object(self):
        organisation = get_request_organisation(self.request)
        return get_object_or_404(
            ComplianceAndCertification,
            alias=self.kwargs["compliance_alias"],
            organisation=organisation,
        )

class UploadDocumentListCreateApiView(ListCreateAPIView):
    serializer_class = UploadDocumentSerializer
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]
    search_fields = ["property__property_name", "document_name"]
    filterset_fields = ["document_category"]

    def get_queryset(self):
        organisation = get_request_organisation(self.request)
        return UploadDocument.objects.filter(
            organisation=organisation
        ).order_by("-created_at")

    def perform_create(self, serializer):
        organisation = get_request_organisation(self.request)
        serializer.save(organisation=organisation)


class UploadDocumentRetrieveAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = UploadDocumentSerializer
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]

    def get_object(self):
        organisation = get_request_organisation(self.request)
        return get_object_or_404(
            UploadDocument,
            alias=self.kwargs["document_alias"],
            organisation=organisation,
        )


class FinanceListView(ListCreateAPIView):
    serializer_class = FinanceSerializer
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]
    search_fields = ["property__property_name"]

    def get_queryset(self):
        organisation = get_request_organisation(self.request)
        return Finance.objects.filter(
            organisation=organisation
        ).order_by("-created_at")

    def perform_create(self, serializer):
        organisation = get_request_organisation(self.request)
        serializer.save(organisation=organisation)


class FinanceDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = FinanceSerializer
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]

    def get_object(self):
        organisation = get_request_organisation(self.request)
        return get_object_or_404(
            Finance,
            alias=self.kwargs["finance_alias"],
            organisation=organisation,
        )


class PropertyOnboardingAPIView(APIView):
    permission_classes = [IsLandlord | IsAdmin | IsSuperAdmin]

    def post(self, request, *args, **kwargs):
        organisation = get_request_organisation(request)
        serializer = PropertyOnboardingSerializer(
            data=request.data,
            context={"request": request, "organisation": organisation},
        )
        serializer.is_valid(raise_exception=True)
        return Response(serializer.save(), status=status.HTTP_200_OK)



class ComplianceAndCertificationShareView(ListCreateAPIView):
    permission_classes = [IsSuperAdmin | IsLandlord | IsAdmin]
    pagination_class = PageNumberPagination

    def get_serializer_class(self):
        if self.request.method == "GET":
            return TenantSerializer
        return ComplianceShareSerializer

    def get_compliance(self):
        organisation = get_request_organisation(self.request)
        return get_object_or_404(
            ComplianceAndCertification,
            alias=self.kwargs["compliance_alias"],
            organisation=organisation,
        )

    def get_queryset(self):
        compliance = self.get_compliance()
        return (
            Tenant.objects.filter(
                organisation=compliance.organisation,
                compliance_shares__compliance=compliance,
            )
            .distinct()
            .order_by("-created_at")
        )

    def create(self, request, *args, **kwargs):
        compliance = self.get_compliance()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant_aliases = serializer.validated_data["tenant"]
        tenants = Tenant.objects.filter(
            alias__in=tenant_aliases,
            organisation=compliance.organisation,
        )
        found = {str(a) for a in tenants.values_list("alias", flat=True)}
        missing = [str(a) for a in tenant_aliases if str(a) not in found]
        if missing:
            raise ValidationError({"tenant": f"Unknown tenant alias(es): {', '.join(missing)}"})

        ComplianceShare.objects.bulk_create(
            [ComplianceShare(compliance=compliance, tenant=tenant) for tenant in tenants],
            ignore_conflicts=True,
        )

        tenant_names = ", ".join(t.get_full_name() for t in tenants)
        return Response(
            {"detail": f"Certificate shared with {tenant_names}."},
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, *args, **kwargs):
        compliance = self.get_compliance()
        tenant = get_object_or_404(
            Tenant,
            alias=request.query_params.get("tenant"),
            organisation=compliance.organisation,
        )

        ComplianceShare.objects.filter(
            tenant=tenant,
            compliance=compliance,
        ).delete()

        return Response(
            {"detail": f"Certificate access removed for {tenant.get_full_name()}."},
            status=status.HTTP_200_OK,
        )