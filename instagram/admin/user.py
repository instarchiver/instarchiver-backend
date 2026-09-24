from django.contrib import admin
from django.contrib import messages
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from instagram.models import User


@admin.register(User)
class InstagramUserAdmin(SimpleHistoryAdmin, ModelAdmin):
    actions_detail = [
        {
            "title": "Actions",
            "items": [
                "update_from_api",
                "update_stories_from_saveapi",
                "update_posts_from_api",
            ],
        },
    ]
    list_display = [
        "username",
        "full_name",
        "instagram_id",
        "is_private",
        "is_verified",
        "follower_count",
        "media_count",
        "view_count",
        "created_at",
        "api_updated_at",
    ]
    list_filter = [
        "is_private",
        "is_verified",
        "allow_auto_update_stories",
        "allow_auto_update_profile",
        "created_at",
        "api_updated_at",
    ]
    search_fields = ["username", "full_name", "instagram_id"]
    readonly_fields = [
        "uuid",
        "instagram_id",
        "full_name",
        "biography",
        "media_count",
        "follower_count",
        "following_count",
        "profile_picture",
        "created_at",
        "updated_at",
        "api_updated_at",
        "raw_api_data",
        "view_count",
    ]
    fieldsets = (
        (
            "General",
            {
                "fields": (
                    ("username", "instagram_id"),
                    (
                        "full_name",
                        "biography",
                    ),
                    "profile_picture",
                    ("is_private", "is_verified"),
                    ("allow_auto_update_stories", "allow_auto_update_profile"),
                    ("media_count", "follower_count", "following_count"),
                ),
                "classes": ["tab"],
            },
        ),
        (
            "Metadata",
            {
                "fields": (
                    "uuid",
                    "created_at",
                    "updated_at",
                    "api_updated_at",
                    "raw_api_data",
                    "view_count",
                ),
                "classes": ["tab"],
            },
        ),
    )
    ordering = ["-created_at"]

    @action(
        description=_("Update Profile"),
        icon="refresh",
        url_path="update-from-api",
        permissions=["change"],
    )
    def update_from_api(self, request: HttpRequest, object_id: str):
        """Update user profile data from Instagram API."""
        try:
            user = User.objects.get(pk=object_id)
            user.update_profile_from_api()
            messages.success(
                request,
                f"Successfully updated {user.username} from Instagram API.",
            )
        except Exception as e:  # noqa: BLE001
            messages.error(
                request,
                "Failed to update user from API: %s" % str(e),  # noqa: UP031
            )

        return redirect(reverse("admin:instagram_user_change", args=(object_id,)))

    @action(
        description=_("Update Stories"),
        icon="refresh",
        url_path="update-stories-from-saveapi",
        permissions=["change"],
    )
    def update_stories_from_saveapi(self, request: HttpRequest, object_id: str):
        """Update user stories from SaveAPI asynchronously."""
        try:
            user = User.objects.get(pk=object_id)
            task_result = user.update_stories_from_saveapi_async()
            messages.success(
                request,
                f"Successfully queued story update task for {user.username}. Task ID: {task_result.id}",  # noqa: E501
            )
        except Exception as e:  # noqa: BLE001
            messages.error(
                request,
                "Failed to queue story update task: %s" % str(e),  # noqa: UP031
            )

        return redirect(reverse("admin:instagram_user_change", args=(object_id,)))

    @action(
        description=_("Update Posts"),
        icon="refresh",
        url_path="update-posts-from-api",
        permissions=["change"],
    )
    def update_posts_from_api(self, request: HttpRequest, object_id: str):
        """Update user posts from Instagram API asynchronously."""
        try:
            user = User.objects.get(pk=object_id)
            task_result = user.update_posts_from_api_async()
            messages.success(
                request,
                f"Successfully queued post update task for {user.username}. Task ID: {task_result.id}",  # noqa: E501
            )
        except Exception as e:  # noqa: BLE001
            messages.error(
                request,
                "Failed to queue post update task: %s" % str(e),  # noqa: UP031
            )

        return redirect(reverse("admin:instagram_user_change", args=(object_id,)))
