from django.urls import path

from api.views.users import (
    UserListCreateAPIView,
    UserRetrieveUpdateDestroyAPIView
)

urlpatterns = [
    path("", UserListCreateAPIView.as_view(), name="user-list-create"),
    path("<uuid:alias>/", UserRetrieveUpdateDestroyAPIView.as_view(), name="user-detail"),
]