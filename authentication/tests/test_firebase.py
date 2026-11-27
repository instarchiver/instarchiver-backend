import contextlib
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import patch

import firebase_admin
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from django.test import override_settings

from authentication import firebase
from settings.models import FirebaseAdminSetting

CONCURRENT_THREAD_COUNT = 8
SOLO_CACHE_TIMEOUT_SECONDS = 60


def _generate_private_key_pem() -> str:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


TEST_PRIVATE_KEY_PEM = _generate_private_key_pem()


def _make_service_account_json(project_id: str) -> str:
    return json.dumps(
        {
            "type": "service_account",
            "project_id": project_id,
            "private_key_id": f"{project_id}-key",
            "private_key": TEST_PRIVATE_KEY_PEM,
            "client_email": (f"firebase-adminsdk@{project_id}.iam.gserviceaccount.com"),
            "client_id": "1234567890",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    )


def _app_name_for_json(raw_json: str) -> str:
    digest = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
    return f"firebase-{digest}"


def _delete_test_app(app_name: str) -> None:
    with contextlib.suppress(ValueError):
        firebase_admin.delete_app(firebase_admin.get_app(app_name))


class FirebaseAppCacheTestCase(TestCase):
    """Tests for thread-safe caching and rotation of Firebase App instances."""

    def setUp(self):
        self.sa_json_one = _make_service_account_json("instarchiver-test-1")
        self.sa_json_two = _make_service_account_json("instarchiver-test-2")
        self.app_names_to_cleanup = [
            _app_name_for_json(self.sa_json_one),
            _app_name_for_json(self.sa_json_two),
        ]
        FirebaseAdminSetting.clear_cache()

    def tearDown(self):
        FirebaseAdminSetting.clear_cache()
        for app_name in self.app_names_to_cleanup:
            _delete_test_app(app_name)

    def _save_service_account_json(self, raw_json: str) -> FirebaseAdminSetting:
        setting = FirebaseAdminSetting.get_solo()
        setting.service_account_json = raw_json
        setting.save()
        return setting

    def test_get_firebase_app_reuses_cached_app_without_deleting(self):
        self._save_service_account_json(self.sa_json_one)

        with (
            patch(
                "authentication.firebase.firebase_admin.initialize_app",
                wraps=firebase_admin.initialize_app,
            ) as mock_init,
            patch(
                "authentication.firebase.firebase_admin.delete_app",
                wraps=firebase_admin.delete_app,
            ) as mock_delete,
        ):
            first_app = firebase._get_firebase_app()  # noqa: SLF001
            second_app = firebase._get_firebase_app()  # noqa: SLF001

        assert first_app is second_app
        assert first_app.name == _app_name_for_json(self.sa_json_one)
        assert mock_init.call_count == 1
        mock_delete.assert_not_called()

    def test_get_firebase_app_rotates_credentials_without_deleting_old_app(self):
        self._save_service_account_json(self.sa_json_one)

        with patch(
            "authentication.firebase.firebase_admin.delete_app",
            wraps=firebase_admin.delete_app,
        ) as mock_delete:
            app_one = firebase._get_firebase_app()  # noqa: SLF001

            self._save_service_account_json(self.sa_json_two)
            app_two = firebase._get_firebase_app()  # noqa: SLF001

            self._save_service_account_json(self.sa_json_one)
            app_one_again = firebase._get_firebase_app()  # noqa: SLF001

        assert app_one is not app_two
        assert app_one.name != app_two.name
        assert app_one.project_id == "instarchiver-test-1"
        assert app_two.project_id == "instarchiver-test-2"
        assert firebase_admin.get_app(app_one.name) is app_one
        assert firebase_admin.get_app(app_two.name) is app_two
        assert app_one_again is app_one
        mock_delete.assert_not_called()

    @override_settings(
        SOLO_CACHE="default",
        SOLO_CACHE_TIMEOUT=SOLO_CACHE_TIMEOUT_SECONDS,
    )
    def test_get_firebase_app_respects_solo_cache_updates_on_save(self):
        FirebaseAdminSetting.clear_cache()
        try:
            self._save_service_account_json(self.sa_json_one)
            app_one = firebase._get_firebase_app()  # noqa: SLF001

            self._save_service_account_json(self.sa_json_two)
            app_two = firebase._get_firebase_app()  # noqa: SLF001

            assert app_one is not app_two
            assert app_two.project_id == "instarchiver-test-2"
        finally:
            FirebaseAdminSetting.clear_cache()

    def test_get_firebase_app_is_thread_safe_on_cold_start(self):
        setting = FirebaseAdminSetting(service_account_json=self.sa_json_one)
        barrier = threading.Barrier(CONCURRENT_THREAD_COUNT)
        original_cert = firebase.credentials.Certificate

        def slow_certificate(data):
            time.sleep(0.02)
            return original_cert(data)

        def worker():
            barrier.wait()
            return firebase._get_firebase_app()  # noqa: SLF001

        with (
            patch(
                "settings.models.FirebaseAdminSetting.get_solo",
                return_value=setting,
            ),
            patch(
                "authentication.firebase.credentials.Certificate",
                side_effect=slow_certificate,
            ),
            patch(
                "authentication.firebase.firebase_admin.initialize_app",
                wraps=firebase_admin.initialize_app,
            ) as mock_init,
            ThreadPoolExecutor(max_workers=CONCURRENT_THREAD_COUNT) as pool,
        ):
            futures = [pool.submit(worker) for _ in range(CONCURRENT_THREAD_COUNT)]
            apps = [future.result() for future in futures]

        assert mock_init.call_count == 1
        assert len({id(app) for app in apps}) == 1

    def test_get_firebase_app_rejects_empty_or_whitespace_json(self):
        for raw_json in ["", "   \n\t"]:
            self._save_service_account_json(raw_json)
            with pytest.raises(
                ImproperlyConfigured,
                match="Firebase service account JSON content not configured",
            ):
                firebase._get_firebase_app()  # noqa: SLF001

    def test_get_firebase_app_rejects_malformed_or_non_dict_json(self):
        invalid_payloads = [
            "{not-valid-json",
            '"/etc/passwd"',
            "[]",
            "123",
            "null",
        ]
        with patch(
            "authentication.firebase.credentials.Certificate",
            wraps=firebase.credentials.Certificate,
        ) as mock_cert:
            for payload in invalid_payloads:
                self._save_service_account_json(payload)
                with pytest.raises(
                    ImproperlyConfigured,
                    match="Invalid Firebase service account JSON content",
                ):
                    firebase._get_firebase_app()  # noqa: SLF001

        mock_cert.assert_not_called()

    def test_get_firebase_app_rejects_invalid_certificate_dict(self):
        self._save_service_account_json(json.dumps({"type": "other"}))
        with pytest.raises(
            ImproperlyConfigured,
            match="Invalid Firebase service account JSON content",
        ):
            firebase._get_firebase_app()  # noqa: SLF001

    def test_get_firebase_app_wraps_settings_access_errors(self):
        with (
            patch(
                "settings.models.FirebaseAdminSetting.get_solo",
                side_effect=RuntimeError("db down"),
            ),
            pytest.raises(
                ImproperlyConfigured,
                match="Cannot access Firebase settings",
            ),
        ):
            firebase._get_firebase_app()  # noqa: SLF001

    def test_get_firebase_app_raises_if_config_cleared_or_corrupted_after_cache(self):
        self._save_service_account_json(self.sa_json_one)
        cached_app = firebase._get_firebase_app()  # noqa: SLF001
        assert cached_app.project_id == "instarchiver-test-1"

        self._save_service_account_json("")
        with pytest.raises(
            ImproperlyConfigured,
            match="Firebase service account JSON content not configured",
        ):
            firebase._get_firebase_app()  # noqa: SLF001

        self._save_service_account_json("{corrupted")
        with pytest.raises(
            ImproperlyConfigured,
            match="Invalid Firebase service account JSON content",
        ):
            firebase._get_firebase_app()  # noqa: SLF001


class FirebaseTokenHelpersTestCase(TestCase):
    """Tests for validate_token() and get_user_info()."""

    def setUp(self):
        self.sa_json = _make_service_account_json("instarchiver-helpers")
        setting = FirebaseAdminSetting.get_solo()
        setting.service_account_json = self.sa_json
        setting.save()
        FirebaseAdminSetting.clear_cache()

    def tearDown(self):
        FirebaseAdminSetting.clear_cache()
        _delete_test_app(_app_name_for_json(self.sa_json))

    def test_validate_token_uses_cached_app_and_returns_claims(self):
        claims = {"uid": "uid-1", "email": "alice@example.com"}
        with patch(
            "authentication.firebase.auth.verify_id_token",
            return_value=claims,
        ) as mock_verify:
            result = firebase.validate_token("valid-id-token")

        assert result == claims
        app = firebase_admin.get_app(_app_name_for_json(self.sa_json))
        mock_verify.assert_called_once_with("valid-id-token", app=app)

    def test_validate_token_wraps_verification_failure(self):
        with (
            patch(
                "authentication.firebase.auth.verify_id_token",
                side_effect=ValueError("bad signature"),
            ),
            pytest.raises(Exception, match="Invalid token"),
        ):
            firebase.validate_token("bad-id-token")

    def test_get_user_info_extracts_claims_without_calling_get_user(self):
        claims = {
            "uid": " user-123 ",
            "email": " alice@example.com ",
            "email_verified": True,
            "name": " Alice Example ",
            "picture": " https://example.com/avatar.png ",
        }
        with (
            patch(
                "authentication.firebase.auth.verify_id_token",
                return_value=claims,
            ) as mock_verify,
            patch("authentication.firebase.auth.get_user") as mock_get_user,
        ):
            result = firebase.get_user_info("valid-id-token")

        assert result == {
            "uid": "user-123",
            "email": "alice@example.com",
            "email_verified": True,
            "name": "Alice Example",
            "photo_url": "https://example.com/avatar.png",
        }
        app = firebase_admin.get_app(_app_name_for_json(self.sa_json))
        mock_verify.assert_called_once_with("valid-id-token", app=app)
        mock_get_user.assert_not_called()

    def test_get_user_info_normalizes_missing_null_and_non_string_claims(self):
        claim_variants: list[dict[str, Any]] = [
            {"uid": "user-1"},
            {
                "uid": "user-2",
                "email": None,
                "email_verified": "true",
                "name": None,
                "picture": None,
            },
            {
                "uid": "user-3",
                "email": "   ",
                "email_verified": False,
                "name": 123,
                "picture": ["https://example.com/a.png"],
            },
        ]
        for claims in claim_variants:
            with patch(
                "authentication.firebase.auth.verify_id_token",
                return_value=claims,
            ):
                result = firebase.get_user_info("valid-id-token")

            assert result == {
                "uid": claims["uid"],
                "email": None,
                "email_verified": False,
                "name": "",
                "photo_url": "",
            }

    def test_get_user_info_raises_when_uid_missing_empty_or_non_string(self):
        for bad_claims in [
            {},
            {"uid": None},
            {"uid": ""},
            {"uid": "   "},
            {"uid": 42},
        ]:
            with (
                patch(
                    "authentication.firebase.auth.verify_id_token",
                    return_value=bad_claims,
                ),
                pytest.raises(ValueError, match="Token missing uid claim"),
            ):
                firebase.get_user_info("valid-id-token")
