from django.contrib import admin

from .models import (
    SubscriptionFeature,
    SubscriptionPlan,
    SubscriptionPlanFeature,
    PaymentCard,
    PaymentTransaction,
)


@admin.register(SubscriptionFeature)
class SubscriptionFeatureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "description", "is_active")
    search_fields = ("code", "name", "description")
    list_filter = ("is_active",)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "alias",
        "name",
        "plan_type",
        "monthly_price",
        "max_properties",
        "max_users",
        "is_active",
    )
    search_fields = ("alias", "name", "description")
    list_filter = ("plan_type", "is_active")


@admin.register(SubscriptionPlanFeature)
class SubscriptionPlanFeatureAdmin(admin.ModelAdmin):
    list_display = ("plan", "feature", "is_included", "value")
    search_fields = ("plan__name", "feature__name")
    list_filter = ("is_included",)


@admin.register(PaymentCard)
class PaymentCardAdmin(admin.ModelAdmin):
    list_display = (
        "alias",
        "card_brand",
        "last_four",
        "expiry_month",
        "expiry_year",
        "is_default",
    )
    search_fields = ("alias", "card_brand", "last_four")
    list_filter = ("card_brand", "is_default")


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "organisation",
        "amount",
        "currency",
        "status",
        "created_at",
    )
    search_fields = ("organisation__name", "id")
    list_filter = ("status", "currency", "created_at")
