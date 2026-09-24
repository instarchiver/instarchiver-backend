from django.urls import path

from telegram_bot.views import TelegramWebhookView

urlpatterns = [
    path("webhook/", TelegramWebhookView.as_view(), name="webhook"),
]


app_name = "telegram_bot"
