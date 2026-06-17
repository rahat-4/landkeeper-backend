from django.urls import path, include

urlpatterns = [
    path("auth/", include("api.urls.auth")),
    path("users/", include("api.urls.users")),
    path("organisation/", include("api.urls.organisation")),
]