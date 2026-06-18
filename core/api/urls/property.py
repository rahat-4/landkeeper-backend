from django.urls import path
from api.views.property import (
    PropertyListCreateAPIView,
    PropertyRetrieveUpdateDestroyAPIView,
    MortgageListCreateAPIView,
    MortgageRetrieveAPIView
)

urlpatterns = [
    path(
        "proprty/",
        PropertyListCreateAPIView.as_view(),
        name="property-list-create"
    ),
    path(
        "proprty/<uuid:alias>/",
        PropertyRetrieveUpdateDestroyAPIView.as_view(),
        name="property-retrieve-update"
    ),
    path(
        "mortgage/",
        MortgageListCreateAPIView.as_view(),
        name="property-list-create"
    ),
    path(
        "mortgage/<uuid:alias>/",
        MortgageRetrieveAPIView.as_view(),
        name="property-retrieve-update"
    ),
]