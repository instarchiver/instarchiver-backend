from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.admin import TabularInline

from payments.models import PricingFeature
from payments.models import PricingPlan


class PricingFeatureInline(TabularInline):
    model = PricingFeature
    extra = 1
    fields = ("label", "is_available", "sort_order")
    tab = True


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
    inlines = [PricingFeatureInline]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "description",
                    ("billing_period", "currency"),
                    ("price", "sort_order"),
                    "is_active",
                    ("created_at", "updated_at"),
                ),
            },
        ),
    )

    readonly_fields = ("created_at", "updated_at")
