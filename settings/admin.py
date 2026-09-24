import requests
from django.contrib import admin
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from solo.admin import SingletonModelAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action

from core.utils import openai

from .models import CoreAPISetting
from .models import FirebaseAdminSetting
from .models import OpenAISetting
from .models import OpenRouterSetting
from .models import StripeSetting
from .models import TelegramSetting


@admin.register(OpenAISetting)
class OpenAISettingAdmin(SingletonModelAdmin, ModelAdmin):
    fieldsets = (
        (
            "OpenAI Configuration",
            {
                "fields": ("api_key", "model_name"),
                "description": "Configure OpenAI API settings",
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at")

    actions_detail = ["check_connection"]

    @action(
        description=_("Check Connection"),
        url_path="check-connection",
    )
    def check_connection(self, request: HttpRequest, object_id: int):
        if openai.check_connection():
            self.message_user(request, _("OpenAI API connection is working."))
        else:
            self.message_user(
                request,
                _("Failed to connect to OpenAI API."),
                level="error",
            )

        return redirect(
            reverse_lazy("admin:settings_openaisetting_change", args=(object_id,)),
        )


@admin.register(CoreAPISetting)
class CoreAPISettingAdmin(SingletonModelAdmin, ModelAdmin):
    fieldsets = (
        (
            "Core API Configuration",
            {
                "fields": ("api_url", "api_token"),
                "description": "Configure Core API settings",
            },
        ),
        (
            "SaveAPI Configuration",
            {
                "fields": ("saveapi_url", "saveapi_api_key"),
                "description": "Configure SaveAPI settings",
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(FirebaseAdminSetting)
class FirebaseAdminSettingAdmin(SingletonModelAdmin, ModelAdmin):
    fieldsets = (
        (
            "Firebase Admin Configuration",
            {
                "fields": (
                    "service_account_json",
                    "service_account_file",
                    "project_id",
                ),
                "description": (
                    "Configure Firebase Admin SDK settings. "
                    "For production, use JSON content field. "
                    "For development, you can upload a file."
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
    readonly_fields = ("service_account_json", "created_at", "updated_at")


@admin.register(OpenRouterSetting)
class OpenRouterSettingAdmin(SingletonModelAdmin, ModelAdmin):
    fieldsets = (
        (
            "OpenRouter Configuration",
            {
                "fields": (
                    "embedding_api_key",
                    "embedding_base_url",
                    "image_embedding_model",
                ),
                "description": "Configure OpenRouter API settings for image embeddings",
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(StripeSetting)
class StripeAdminSetting(SingletonModelAdmin, ModelAdmin):
    fieldsets = (
        (
            "Stripe Configuration",
            {
                "fields": ("api_key", "webhook_secret"),
                "description": "Configure Stripe API settings",
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(TelegramSetting)
class TelegramSettingAdmin(SingletonModelAdmin, ModelAdmin):
    fieldsets = (
        (
            "Telegram Bot Configuration",
            {
                "fields": ("bot_token", "webhook_secret"),
                "description": (
                    "Configure the Telegram bot. Save first, then use Set Webhook "
                    "to point Telegram at this server."
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at")

    actions_detail = ["set_webhook"]

    @action(
        description=_("Set Webhook"),
        url_path="set-webhook",
    )
    def set_webhook(self, request: HttpRequest, object_id: int):
        redirect_url = reverse_lazy(
            "admin:settings_telegramsetting_change",
            args=(object_id,),
        )
        webhook_url = request.build_absolute_uri(reverse("telegram_bot:webhook"))
        webhook_url = "https://741a-103-156-219-208.ngrok-free.app/telegram/webhook/"

        if not webhook_url.startswith("https://"):
            self.message_user(
                request,
                _("Telegram only accepts HTTPS webhooks. Got: %(url)s")
                % {"url": webhook_url},
                level="error",
            )
            return redirect(redirect_url)

        try:
            result = TelegramSetting.get_solo().set_webhook(webhook_url)
        except (ImproperlyConfigured, requests.RequestException) as e:
            self.message_user(
                request,
                _("Failed to set webhook: %(error)s") % {"error": e},
                level="error",
            )
            return redirect(redirect_url)

        if result.get("ok"):
            self.message_user(
                request,
                _("Webhook set to %(url)s") % {"url": webhook_url},
            )
        else:
            self.message_user(
                request,
                _("Telegram rejected the webhook: %(description)s")
                % {"description": result.get("description", "unknown error")},
                level="error",
            )

        return redirect(redirect_url)
