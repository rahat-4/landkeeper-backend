from django.urls import path
from api.views.organisation import (
    OrganisationDetailView,
    OrganisationUserListCreateView,
    OrganisationUserDetailView,
    OrganisationListView,
)

urlpatterns = [
    path("", OrganisationListView.as_view(), name="organisation-list"),
    path(
        "<slug:organisation_slug>/",
        OrganisationDetailView.as_view(),
        name="organisation-detail",
    ),
    # path(
    #     "<slug:organisation_slug>/users/",
    #      OrganisationUserListCreateView.as_view(),
    #      name="organisation-user-list"
    # ),
    # path(
    #     "<slug:organisation_slug>/users/<int:pk>/",
    #     OrganisationUserDetailView.as_view(),
    #     name="organisation-user-detail"
    # ),
]
