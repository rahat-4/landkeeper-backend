from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.property.models import (
    Property,
    Mortgage,
    Tenant,
    TenantDocument
)
from api.serializers.property import (
    PropertySerializer,
    MortgageSerializers,
    TenantSerializer,
    TenantDocumentSerializer,
)


class PropertyListCreateAPIView(ListCreateAPIView):
    serializer_class = PropertySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Property.objects.all()

class PropertyRetrieveUpdateDestroyAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = PropertySerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "alias"

    def get_object(self):
        return get_object_or_404(
            Property,
            alias=self.kwargs["alias"]
        )

class MortgageListCreateAPIView(ListCreateAPIView):
    serializer_class = MortgageSerializers
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Mortgage.objects.all()

class MortgageRetrieveAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = MortgageSerializers
    permission_classes = [IsAuthenticated]
    lookup_field = "alias"
    def get_object(self):
        return get_object_or_404(
            Mortgage,
            alias=self.kwargs["alias"]
        )

class TenantListCreateAPIView(ListCreateAPIView):
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Tenant.objects.all()

class TenantRetrieveAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "alias"

    def get_object(self):
        return get_object_or_404(
            Tenant,
            alias=self.kwargs["alias"]
        )

class TenantDocumentListCreateAPIView(ListCreateAPIView):
    serializer_class = TenantDocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TenantDocument.objects.filter(tenant__alias=self.kwargs["alias"])

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['tenant'] = get_object_or_404(Tenant, alias=self.kwargs["alias"])
        return context

    def create(self, request, *args, **kwargs):
        tenant = get_object_or_404(Tenant, alias=self.kwargs["alias"])
        files = request.FILES.getlist('files')

        if not files:
            return Response(
                {"files": "No files provided."},
                status=status.HTTP_400_BAD_REQUEST
            )

        documents = [
            TenantDocument.objects.create(
                tenant=tenant,
                file=file,
                description=request.data.get('description', '')
            )
            for file in files
        ]

        return Response(
            TenantDocumentSerializer(
                documents,
                many=True,
                context=self.get_serializer_context()
            ).data,
            status=status.HTTP_201_CREATED
        )
class TenantDocumentRetrieveAPIView(RetrieveUpdateDestroyAPIView):
    serializer_class = TenantDocumentSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "alias"

    def get_object(self):
        return get_object_or_404(
            TenantDocument,
            alias=self.kwargs["document_alias"],
            tenant__alias=self.kwargs["alias"]
        )