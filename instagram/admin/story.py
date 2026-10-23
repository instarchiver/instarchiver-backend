from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import AutocompleteSelectMultipleFilter

from instagram.models import Story


@admin.register(Story)
class StoryAdmin(ModelAdmin):
    list_display = [
        "story_id",
        "is_flagged",
        "user",
        "view_count",
        "created_at",
        "story_created_at",
    ]
    list_filter = [
        ["user", AutocompleteSelectMultipleFilter],
        "is_flagged",
        "created_at",
        "story_created_at",
    ]
    search_fields = [
        "story_id",
        "user__username",
    ]
    readonly_fields = [
        "story_id",
        "user",
        "created_at",
        "story_created_at",
        "raw_api_data",
        "blur_data_url",
        "embedding_token_usage",
        "moderation_result",
        "view_count",
    ]
    fieldsets = (
        (
            "General",
            {
                "fields": (
                    ("story_id", "user"),
                    "story_created_at",
                    "thumbnail",
                    "media",
                    "blur_data_url",
                    ("embedding", "embedding_token_usage"),
                ),
                "classes": ["tab"],
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "created_at",
                    "raw_api_data",
                    "view_count",
                ),
                "classes": ["tab"],
            },
        ),
        (
            "Moderation",
            {
                "fields": (
                    "moderated_at",
                    "is_flagged",
                    "moderation_result",
                ),
                "classes": ["tab"],
            },
        ),
    )
    ordering = ["-created_at"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .defer(
                "embedding",
                "raw_api_data",
                "moderation_result",
                "user__raw_api_data",
            )
        )
