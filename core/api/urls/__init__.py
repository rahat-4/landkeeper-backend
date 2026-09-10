from django.urls import path, include

urlpatterns = [
    path("/auth", include("api.urls.auth")),
    path("/organisation", include("api.urls.organisation")),
    path("/filters", include("api.urls.filters")),
    path("", include("api.urls.property")),
    path("/support-tickets", include("api.urls.support_tickets")),
    path("/tenant", include("api.urls.tenants")),
    path("/notifications", include("api.urls.notifications")),
    path("/templates", include("api.urls.documents")),
    path("/permissions", include("api.urls.permissions")),
    # path("/ambassador", include("api.urls.ambassador")),
    path("/subscription", include("api.urls.subscription")),
]
