from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from payments.models import GatewayOption
from payments.models import PaymentSetting


@admin.register(PaymentSetting)
class PaymentSettingAdmin(ModelAdmin, SimpleHistoryAdmin):
    model = PaymentSetting


@admin.register(GatewayOption)
class GatewayOptionAdmin(ModelAdmin, SimpleHistoryAdmin):
    model = GatewayOption

    list_display = ("name", "is_active", "created_at", "updated_at")
