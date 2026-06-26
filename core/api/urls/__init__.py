from django.urls import path, include

urlpatterns = [
    path("/auth", include("api.urls.auth")),
    path("/organisation", include("api.urls.organisation")),
    path("/filters", include("api.urls.filters")),
    path("", include("api.urls.property")),
]
