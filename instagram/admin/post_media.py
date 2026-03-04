from django.contrib import admin
from unfold.admin import ModelAdmin

from instagram.models import PostMedia


@admin.register(PostMedia)
class PostMediaAdmin(ModelAdmin):
    """Admin interface for PostMedia model."""

    list_display = [
        "id",
        "post",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "post__id",
        "post__user__username",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "thumbnail_url",
        "media_url",
        "width",
        "height",
    ]
    fieldsets = (
        (
            "General",
            {
                "fields": (
                    ("post", "reference"),
                    ("thumbnail_url", "media_url"),
                    ("width", "height"),
                    ("thumbnail", "media"),
                ),
                "classes": ["tab"],
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ["tab"],
            },
        ),
    )
    autocomplete_fields = ["post"]
    ordering = ["-created_at"]
