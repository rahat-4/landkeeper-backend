from django.urls import path

from api.views.subscription import (
    SelectSubscriptionView,
    StripeWebhookView,
    SubscriptionPlanListView,
    LandlordPaymentCardListAPIView,
    LandlordPaymentCardDeleteAPIView,
    LandlordBillingHistoryAPIView,
    LandlordSubscriptionAPIView,
    LandlordSubscriptionValidationAPIView,
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
        "/stripe",
        StripeWebhookView.as_view(),
        name="stripe-webhook",
    ),
    path(
        "/cards",
        LandlordPaymentCardListAPIView.as_view(),
        name="landlord-payment-card-list",
    ),
    path(
        "cards/<uuid:alias>",
        LandlordPaymentCardDeleteAPIView.as_view(),
        name="landlord-payment-card-delete",
    ),
    path(
        "/billing-history",
        LandlordBillingHistoryAPIView.as_view(),
        name="landlord-billing-history",
    ),
    path(
        "",
        LandlordSubscriptionAPIView.as_view(),
        name="landlord-subscription",
    ),
    path(
        "/validation",
        LandlordSubscriptionValidationAPIView.as_view(),
        name="landlord-subscription-validation",
    ),
]
