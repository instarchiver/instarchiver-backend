from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from telegram_bot.models import TelegramUser


@admin.register(TelegramUser)
class TelegramUserAdmin(SimpleHistoryAdmin, ModelAdmin):
    list_display = (
        "telegram_id",
        "username",
        "first_name",
        "user",
        "created_at",
    )
    list_filter = ("is_bot", "is_premium", "created_at")
    search_fields = ("telegram_id", "username", "first_name", "user__username")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
