from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from payments.models import PricingPlan


@admin.register(PricingPlan)
class PricingPlanAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "id",
        "name",
        "billing_period",
        "price",
        "currency",
        "is_active",
        "sort_order",
    )
    list_filter = ("billing_period", "currency", "is_active")
    search_fields = ("name",)

    fieldsets = (
        (
            "General",
            {
                "fields": (
                    "name",
                    "description",
                    ("billing_period", "currency"),
                    ("price", "sort_order"),
                    "features",
                    "is_active",
                    ("created_at", "updated_at"),
                ),
                "classes": ["tab"],
            },
        ),
    )

    readonly_fields = ("created_at", "updated_at")
