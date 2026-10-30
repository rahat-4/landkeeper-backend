from django.urls import path

from ..views.filters import PropertyFilterListView, PropertyRoomFilterListView

urlpatterns = [
    path(
        "/properties/<uuid:property_alias>/rooms",
        PropertyRoomFilterListView.as_view(),
        name="property-room-filters",
    ),
    path("/properties", PropertyFilterListView.as_view(), name="property-filters"),
]
