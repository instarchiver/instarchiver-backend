from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.admin import StackedInline

from instagram.models import Post
from instagram.models import PostMedia


class PostMediaInline(StackedInline):
    """Inline admin for PostMedia."""

    model = PostMedia
    extra = 0
    fields = [
        "width",
        "height",
        "thumbnail",
        "media",
    ]
    readonly_fields = [
        "width",
        "height",
        "thumbnail_url",
        "media_url",
    ]
    tab = True


@admin.register(Post)
class PostAdmin(SimpleHistoryAdmin, ModelAdmin):
    """Admin interface for Post model."""

    list_display = [
        "id",
        "user",
        "variant",
        "is_flagged",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "variant",
        "is_flagged",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "id",
        "user__username",
        "user__full_name",
    ]
    readonly_fields = [
        "id",
        "user",
        "created_at",
        "updated_at",
        "thumbnail_url",
        "variant",
        "raw_data",
        "blur_data_url",
        "post_created_at",
        "width",
        "height",
        "embedding_token_usage",
        "caption",
        "moderation_result",
    ]
    fieldsets = (
        (
            "General",
            {
                "fields": (
                    ("id", "post_created_at"),
                    ("user", "variant"),
                    ("width", "height"),
                    "thumbnail_url",
                    ("thumbnail", "caption"),
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
                    ("created_at", "updated_at"),
                    "raw_data",
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
    inlines = [PostMediaInline]
    ordering = ["-post_created_at", "-created_at"]
