from django.contrib import admin

from .models import Organisation, OrganisationUser, OrganisationSubscription


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at", "updated_at")


@admin.register(OrganisationUser)
class OrganisationUserAdmin(admin.ModelAdmin):
    list_display = ("user", "organisation", "role", "created_at", "updated_at")
    list_filter = ("role", "organisation")
    search_fields = (
        "user__email",
        "organisation__name",
    )


@admin.register(OrganisationSubscription)
class OrganisationSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "organisation",
        "plan",
        "status",
        "stripe_subscription_id",
        "stripe_checkout_session_id",
        "started_at",
        "current_period_start",
        "current_period_end",
        "cancelled_at",
        "created_at",
        "updated_at",
    )
    search_fields = ("organisation__name", "plan__name")
