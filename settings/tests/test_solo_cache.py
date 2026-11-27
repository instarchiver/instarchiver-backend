import ast
import tempfile
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.cache import caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

from settings.models import CoreAPISetting
from settings.models import FirebaseAdminSetting
from settings.models import FrontendSetting

DjangoUser = get_user_model()

SOLO_CACHE_TIMEOUT_SECONDS = 60


def _read_production_assignments() -> dict[str, ast.expr]:
    production_path = Path(settings.BASE_DIR) / "config" / "settings" / "production.py"
    tree = ast.parse(production_path.read_text(encoding="utf-8"))
    assignments: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
    return assignments


class SoloCacheConfigTest(TestCase):
    def test_solo_cache_disabled_in_test_settings(self):
        assert getattr(settings, "SOLO_CACHE", None) is None

    def test_production_settings_configures_solo_cache(self):
        assignments = _read_production_assignments()

        assert "SOLO_CACHE" in assignments
        assert "SOLO_CACHE_TIMEOUT" in assignments
        assert "CACHES" in assignments

        solo_cache = ast.literal_eval(assignments["SOLO_CACHE"])
        solo_timeout = ast.literal_eval(assignments["SOLO_CACHE_TIMEOUT"])
        caches_node = assignments["CACHES"]
        assert isinstance(caches_node, ast.Dict)
        cache_aliases = {
            key.value
            for key in caches_node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }

        assert solo_cache == "default"
        assert solo_cache in cache_aliases
        assert type(solo_timeout) is int
        assert solo_timeout == SOLO_CACHE_TIMEOUT_SECONDS


@override_settings(SOLO_CACHE="default", SOLO_CACHE_TIMEOUT=SOLO_CACHE_TIMEOUT_SECONDS)
class SoloCacheBehaviorTest(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_get_solo_caches_instance(self):
        setting = CoreAPISetting.get_solo()
        setting.api_url = "https://initial.example.com"
        setting.save()
        cache.clear()

        first = CoreAPISetting.get_solo()
        assert first.api_url == "https://initial.example.com"
        assert caches["default"].get(CoreAPISetting.get_cache_key()) is not None

        with self.assertNumQueries(0):
            second = CoreAPISetting.get_solo()

        assert second.api_url == "https://initial.example.com"

    def test_save_updates_cache(self):
        setting = CoreAPISetting.get_solo()
        setting.api_url = "https://saved.example.com"
        setting.save()

        with self.assertNumQueries(0):
            cached = CoreAPISetting.get_solo()

        assert cached.api_url == "https://saved.example.com"

    def test_queryset_update_requires_clear_cache(self):
        setting = CoreAPISetting.get_solo()
        setting.api_url = "https://before-update.example.com"
        setting.save()
        assert CoreAPISetting.get_solo().api_url == "https://before-update.example.com"

        CoreAPISetting.objects.update(api_url="https://updated.example.com")

        with self.assertNumQueries(0):
            stale = CoreAPISetting.get_solo()
        assert stale.api_url == "https://before-update.example.com"

        CoreAPISetting.clear_cache()
        fresh = CoreAPISetting.get_solo()
        assert fresh.api_url == "https://updated.example.com"

    def test_delete_clears_cache(self):
        setting = CoreAPISetting.get_solo()
        setting.api_url = "https://to-delete.example.com"
        setting.save()
        assert CoreAPISetting.get_solo().api_url == "https://to-delete.example.com"

        setting.delete()

        assert caches["default"].get(CoreAPISetting.get_cache_key()) is None
        recreated = CoreAPISetting.get_solo()
        assert recreated.api_url == ""

    def test_cache_miss_or_none_falls_back_to_database(self):
        setting = CoreAPISetting.get_solo()
        setting.api_url = "https://fallback.example.com"
        setting.save()

        with patch.object(caches["default"], "get", return_value=None):
            fetched = CoreAPISetting.get_solo()

        assert fetched.api_url == "https://fallback.example.com"


@override_settings(SOLO_CACHE="default", SOLO_CACHE_TIMEOUT=SOLO_CACHE_TIMEOUT_SECONDS)
class SoloCacheAdminSaveTest(TestCase):
    def setUp(self):
        cache.clear()
        self.superuser = DjangoUser.objects.create_superuser(
            username="soloadmin",
            password="testpassword123",  # noqa: S106
            email="soloadmin@example.com",
        )
        self.client.force_login(self.superuser)

    def tearDown(self):
        cache.clear()

    def test_core_api_setting_admin_save_updates_cache(self):
        setting = CoreAPISetting.get_solo()
        setting.api_url = "https://old-admin.example.com"
        setting.save()
        assert CoreAPISetting.get_solo().api_url == "https://old-admin.example.com"

        url = reverse("admin:settings_coreapisetting_change", args=(setting.pk,))
        response = self.client.post(
            url,
            data={
                "api_url": "https://new-admin.example.com",
                "api_token": "tok-1",
                "saveapi_url": "https://save.example.com",
                "saveapi_api_key": "key-1",
            },
        )

        assert response.status_code == HTTPStatus.FOUND

        with self.assertNumQueries(0):
            cached = CoreAPISetting.get_solo()

        assert cached.api_url == "https://new-admin.example.com"
        assert cached.saveapi_api_key == "key-1"

    def test_firebase_admin_setting_admin_save_and_resave_update_cache(self):
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            self.settings(MEDIA_ROOT=tmpdir),
        ):
            setting = FirebaseAdminSetting.get_solo()
            setting.project_id = "old-project"
            setting.save()
            assert FirebaseAdminSetting.get_solo().project_id == "old-project"

            url = reverse(
                "admin:settings_firebaseadminsetting_change",
                args=(setting.pk,),
            )
            upload = SimpleUploadedFile(
                "sa.json",
                b'{"project_id": "demo-1"}',
                content_type="application/json",
            )
            response = self.client.post(
                url,
                data={
                    "service_account_file": upload,
                    "project_id": "demo-1",
                },
            )

            assert response.status_code == HTTPStatus.FOUND

            with self.assertNumQueries(0):
                cached = FirebaseAdminSetting.get_solo()

            assert cached.service_account_json == '{"project_id": "demo-1"}'
            assert cached.project_id == "demo-1"

            resave_response = self.client.post(
                url,
                data={"project_id": "demo-2"},
            )

            assert resave_response.status_code == HTTPStatus.FOUND

            with self.assertNumQueries(0):
                resaved = FirebaseAdminSetting.get_solo()

            assert resaved.project_id == "demo-2"
            assert resaved.service_account_json == '{"project_id": "demo-1"}'

    def test_frontend_setting_admin_save_updates_cache(self):
        changelist_url = reverse("admin:settings_frontendsetting_changelist")
        changelist_response = self.client.get(changelist_url, follow=True)
        assert changelist_response.status_code == HTTPStatus.OK

        setting = FrontendSetting.get_solo()
        assert setting.allow_add_user is True

        change_url = reverse(
            "admin:settings_frontendsetting_change",
            args=(setting.pk,),
        )

        disable_response = self.client.post(change_url, data={})
        assert disable_response.status_code == HTTPStatus.FOUND

        with self.assertNumQueries(0):
            disabled = FrontendSetting.get_solo()
        assert disabled.allow_add_user is False

        enable_response = self.client.post(change_url, data={"allow_add_user": "on"})
        assert enable_response.status_code == HTTPStatus.FOUND

        with self.assertNumQueries(0):
            enabled = FrontendSetting.get_solo()
        assert enabled.allow_add_user is True

        history_records = list(
            FrontendSetting.history.order_by("history_date", "history_id"),
        )
        assert [record.allow_add_user for record in history_records] == [
            True,
            False,
            True,
        ]
        assert history_records[-1].history_user == self.superuser

        history_url = reverse("admin:settings_frontendsetting_history")
        history_response = self.client.get(history_url)
        assert history_response.status_code == HTTPStatus.OK
        assert "simple_history/object_history.html" in [
            template.name for template in history_response.templates
        ]

        simple_history_url = reverse(
            "admin:settings_frontendsetting_simple_history",
            args=(setting.pk, history_records[-1].pk),
        )
        simple_history_response = self.client.get(simple_history_url)
        assert simple_history_response.status_code == HTTPStatus.OK
