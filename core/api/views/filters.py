from rest_framework.generics import ListAPIView
from rest_framework.exceptions import NotFound

from apps.property.models import Property

from ..serializers.filters import PropertyFilterSerializer


class PropertyFilterListView(ListAPIView):
    serializer_class = PropertyFilterSerializer
    permission_classes = []
    search_fields = ["property_name"]
    pagination_class = None

    def get_queryset(self):
        organisation = self.request.user.get_organisation()
        if not organisation:
            raise NotFound("Organisation not found for the user.")
        return Property.objects.filter(organisation=organisation)
