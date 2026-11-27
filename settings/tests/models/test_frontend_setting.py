from django.test import TestCase

from settings.models import FrontendSetting


class FrontendSettingModelTest(TestCase):
    def test_default_allow_add_user_is_true(self):
        setting = FrontendSetting.get_solo()

        assert setting.allow_add_user is True
        assert setting.created_at is not None
        assert setting.updated_at is not None

    def test_singleton_behavior(self):
        FrontendSetting.objects.all().delete()

        first = FrontendSetting.get_solo()
        second = FrontendSetting.get_solo()

        assert first.pk == 1
        assert second.pk == first.pk
        assert FrontendSetting.objects.count() == 1

    def test_str_and_verbose_name(self):
        setting = FrontendSetting.get_solo()

        assert str(setting) == "Frontend Settings"
        assert FrontendSetting._meta.verbose_name == "Frontend Setting"  # noqa: SLF001

    def test_history_records_changes(self):
        setting = FrontendSetting.get_solo()
        setting.allow_add_user = False
        setting.save()

        values = list(
            FrontendSetting.history.order_by("history_date", "history_id").values_list(
                "allow_add_user",
                flat=True,
            ),
        )
        assert values == [True, False]
