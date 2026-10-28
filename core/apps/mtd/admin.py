from django.contrib import admin

from apps.mtd.models import MTDReport


@admin.register(MTDReport)
class MTDReportAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "organisation",
        "tax_year",
        "quarter",
        "confirmed_by_name",
        "confirmed_at",
        "updated_at",
    ]
    list_filter = ["quarter", "tax_year"]
    search_fields = ["organisation__name", "confirmed_by_name"]
    readonly_fields = ["alias", "created_at", "updated_at", "created_by"]
    filter_horizontal = ["properties"]
    ordering = ["-tax_year", "-quarter"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("organisation")
