from django.urls import path
from api.views.organisation import (
    OrganisationDetailView,
    OrganisationUserListView,
    OrganisationUserDetailView,
    OrganisationInviteUserView,
    OrganisationListView,
    StripeConnectOnboardingView,
    StripeConnectStatusView,
)

urlpatterns = [
    path(
    "/list",
    OrganisationListView.as_view(),
    name="organisation-list",
    ),
    path(
        "",
        OrganisationDetailView.as_view(),
        name="organisation-detail",
    ),
    path(
        "/users",
        OrganisationUserListView.as_view(),
        name="organisation-user-list",
    ),
    path(
        "/invite-users",
        OrganisationInviteUserView.as_view(),
        name="organisation-invite-user-list",
    ),
    path(
        "/users/<uuid:user_alias>",
        OrganisationUserDetailView.as_view(),
        name="organisation-user-detail",
    ),
    path(
        "/stripe-onboarding",
        StripeConnectOnboardingView.as_view(),
        name="organisation-stripe-onboarding",
    ),
    path(
        "/stripe-connect-status",
        StripeConnectStatusView.as_view(),
        name="organisation-stripe-connect-status",
    )
]