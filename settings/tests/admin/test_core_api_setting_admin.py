from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.contrib.messages import constants as message_constants
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from core.utils.saveapi import SaveAPIError
from settings.admin import CoreAPISettingAdmin
from settings.models import CoreAPISetting

DjangoUser = get_user_model()

ME_RESPONSE = {
    "success": True,
    "key": {"prefix": "sk_live_7t-5o1", "test_mode": False},
    "plan": {
        "code": "free",
        "name": "Free",
        "rate_per_min": 10,
        "platforms": ["instagram"],
    },
    "credits": {"remaining": 242, "expiring_soon": None},
}


class TestCheckSaveAPIConnection(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = CoreAPISettingAdmin(CoreAPISetting, None)
        self.setting = CoreAPISetting.get_solo()
        self.superuser = DjangoUser.objects.create_superuser(
            username="adminsuper",
            password="testpassword123",  # noqa: S106
            email="adminsuper@example.com",
        )

    def _request(self):
        request = self.factory.get("/")
        request.user = self.superuser
        request.session = {}
        request._messages = FallbackStorage(request)  # noqa: SLF001
        return request

    def _run(self, **patch_kwargs):
        request = self._request()
        with patch("settings.admin.saveapi.get_me", **patch_kwargs):
            response = self.admin.check_saveapi_connection(
                request,
                object_id=self.setting.pk,
            )
        messages = list(get_messages(request))
        assert len(messages) == 1
        return response, messages[0]

    def test_success_shows_account_details(self):
        response, message = self._run(return_value=ME_RESPONSE)

        assert message.level == message_constants.SUCCESS
        text = str(message)
        assert "Free" in text
        assert "10 requests/min" in text
        assert "242" in text
        assert "sk_live_7t-5o1 (live)" in text
        assert "Expiring soon" not in text
        assert response.status_code == 302  # noqa: PLR2004
        assert response.url == reverse(
            "admin:settings_coreapisetting_change",
            args=(self.setting.pk,),
        )

    def test_success_shows_test_mode_and_expiring_credits(self):
        data = {
            **ME_RESPONSE,
            "key": {"prefix": "sk_test_abc", "test_mode": True},
            "credits": {"remaining": 5, "expiring_soon": 3},
        }
        _, message = self._run(return_value=data)

        text = str(message)
        assert "sk_test_abc (test)" in text
        assert "Expiring soon: 3" in text

    def test_null_nested_fields_do_not_crash(self):
        _, message = self._run(
            return_value={"success": True, "key": None, "plan": None, "credits": None},
        )

        assert message.level == message_constants.SUCCESS
        assert "unknown" in str(message)

    def test_unsuccessful_response_is_error(self):
        _, message = self._run(return_value={"success": False})

        assert message.level == message_constants.ERROR

    def test_non_dict_response_is_error(self):
        _, message = self._run(return_value=["unexpected"])

        assert message.level == message_constants.ERROR

    def test_errors_are_reported(self):
        errors = [
            SaveAPIError("INVALID_KEY", "Bad key", status_code=401),
            ImproperlyConfigured("SaveAPI API key is not configured in settings"),
            requests.ConnectionError("connection refused"),
            ValueError("not JSON"),
        ]
        for error in errors:
            with self.subTest(error=error):
                response, message = self._run(side_effect=error)

                assert message.level == message_constants.ERROR
                assert "SaveAPI connection failed" in str(message)
                assert response.status_code == 302  # noqa: PLR2004


class TestCheckSaveAPIConnectionRouting(TestCase):
    def setUp(self):
        self.setting = CoreAPISetting.get_solo()
        self.url = reverse(
            "admin:settings_coreapisetting_check_saveapi_connection",
            args=(self.setting.pk,),
        )

    @patch("settings.admin.saveapi.get_me", return_value=ME_RESPONSE)
    def test_superuser_can_run_action(self, mock_get_me):
        superuser = DjangoUser.objects.create_superuser(
            username="adminsuper",
            password="testpassword123",  # noqa: S106
            email="adminsuper@example.com",
        )
        self.client.force_login(superuser)

        response = self.client.get(self.url)

        assert response.status_code == 302  # noqa: PLR2004
        mock_get_me.assert_called_once()

    @patch("settings.admin.saveapi.get_me", return_value=ME_RESPONSE)
    def test_staff_without_change_permission_is_denied(self, mock_get_me):
        staff = DjangoUser.objects.create_user(
            username="staff",
            password="testpassword123",  # noqa: S106
            email="staff@example.com",
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.get(self.url)

        assert response.status_code == 403  # noqa: PLR2004
        mock_get_me.assert_not_called()
