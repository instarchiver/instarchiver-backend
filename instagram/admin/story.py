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
        "thumbnail_insight",
        "thumbnail_insight_token_usage",
        "embedding_token_usage",
        "moderation_result",
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
                    ("thumbnail_insight", "thumbnail_insight_token_usage"),
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
