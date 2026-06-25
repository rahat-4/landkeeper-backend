from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.property.models import (
    Property,
    Mortgage,
    Tenant,
    ComplianceAndCertification,
    UploadDocument,
    Finance,
)
from api.serializers.property import (
    PropertySerializer,
    MortgageSerializers,
    TenantSerializer,
    ComplianceAndCertificationSerializers,
    UploadDocumentSerializer,
    FinanceSerializer,
)


class PropertyListView(ListCreateAPIView):
    serializer_class = PropertySerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["property_type", "status"]
    search_fields = ["property_name", "address"]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        return Property.objects.filter(organisation=organisation)

    def perform_create(self, serializer):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        serializer.save(organisation=organisation)


class PropertyDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = PropertySerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_object_or_404(Property, alias=self.kwargs["property_alias"])


class MortgageListView(ListCreateAPIView):
    serializer_class = MortgageSerializers
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        return Mortgage.objects.filter(organisation=organisation)

    def perform_create(self, serializer):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        serializer.save(organisation=organisation)


class MortgageDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = MortgageSerializers
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_object_or_404(Mortgage, alias=self.kwargs["mortgage_alias"])


class TenantListView(ListCreateAPIView):
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ["first_name", "last_name", "email", "phone"]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        return Tenant.objects.filter(organisation=organisation)

    def perform_create(self, serializer):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        serializer.save(organisation=organisation)


class TenantDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_object_or_404(Tenant, alias=self.kwargs["tenant_alias"])


class ComplianceAndCertificationListView(ListCreateAPIView):
    serializer_class = ComplianceAndCertificationSerializers
    permission_classes = [IsAuthenticated]
    search_fields = ["certification_type", "notes", "certification_number"]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        return ComplianceAndCertification.objects.filter(organisation=organisation)

    def perform_create(self, serializer):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        serializer.save(organisation=organisation)


class ComplianceAndCertificationDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = ComplianceAndCertificationSerializers
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_object_or_404(
            ComplianceAndCertification, alias=self.kwargs["compliance_alias"]
        )


class UploadDocumentListCreateApiView(ListCreateAPIView):
    serializer_class = UploadDocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        return UploadDocument.objects.filter(organisation=organisation)

    def perform_create(self, serializer):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")

        uploaded_files = self.request.FILES.getlist("uploaded_files")
        serializer.save(organisation=organisation, uploaded_files=uploaded_files)


class UploadDocumentRetrieveAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = UploadDocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_object_or_404(UploadDocument, alias=self.kwargs["document_alias"])

    def perform_update(self, serializer):
        uploaded_files = self.request.FILES.getlist("uploaded_files")
        serializer.save(uploaded_files=uploaded_files)


class FinanceListView(ListCreateAPIView):
    serializer_class = FinanceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        return Finance.objects.filter(organisation=organisation)

    def perform_create(self, serializer):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        serializer.save(organisation=organisation)


class FinanceDetailView(RetrieveUpdateDestroyAPIView):
    serializer_class = FinanceSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return get_object_or_404(Finance, alias=self.kwargs["finance_alias"])
