from django.contrib import admin
from unfold.admin import ModelAdmin

from instagram.models import UserFollow


@admin.register(UserFollow)
class UserFollowAdmin(ModelAdmin):
    list_display = [
        "follower",
        "following",
        "is_active",
        "first_seen_at",
        "last_seen_at",
    ]
    list_filter = ["is_active"]
    search_fields = ["follower__username", "following__username"]
    raw_id_fields = ["follower", "following"]
    readonly_fields = ["first_seen_at", "last_seen_at"]
