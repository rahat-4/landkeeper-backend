from django.shortcuts import get_object_or_404
from rest_framework.exceptions import NotFound
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView
)
from rest_framework.permissions import IsAuthenticated
from apps.property.models import (
    Property,
    Mortgage
)
from api.serializers.property import (
    PropertySerializer,
    MortgageSerializers
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