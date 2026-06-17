from django.urls import path
from api.views.organisation import (
    OrganisationOnboardingListCreateAPIView,
    OrganisationOnboardingDetailAPIView
)

urlpatterns = [
    path(
        "onboard/",
        OrganisationOnboardingListCreateAPIView.as_view(),
        name="organisation-list-create"
    ),
    path(
        "onboard/<slug:slug>/",
         OrganisationOnboardingDetailAPIView.as_view(),
        name="organisation-detail"
    ),
]