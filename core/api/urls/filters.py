from django.urls import path

from ..views.filters import PropertyFilterListView

urlpatterns = [
    path("/properties", PropertyFilterListView.as_view(), name="property-filters"),
]
