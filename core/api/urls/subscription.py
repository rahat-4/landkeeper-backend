from django.urls import path

from api.views.subscription import (
    SubscriptionPlanListView,
    SelectSubscriptionView,
    SubscriptionStatusView,
    StripeWebhookView,
)

urlpatterns = [
    path(
        "/plans",
        SubscriptionPlanListView.as_view(),
        name="subscription-plan-list",
    ),
    path(
        "/plans/select",
        SelectSubscriptionView.as_view(),
        name="select-subscription",
    ),
    path(
        "/status",
        SubscriptionStatusView.as_view(),
        name="subscription-status",
    ),
    path(
        "/stripe",
        StripeWebhookView.as_view(),
        name="stripe-webhook",
    ),
]
