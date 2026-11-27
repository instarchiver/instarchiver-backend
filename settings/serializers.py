from rest_framework import serializers

from settings.models import FrontendSetting


class FrontendSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = FrontendSetting
        fields = ("allow_add_user",)
        read_only_fields = ("allow_add_user",)
