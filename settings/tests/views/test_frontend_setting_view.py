from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from settings.models import FrontendSetting


class FrontendSettingViewTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("settings:frontend")

    def test_anonymous_get_returns_default_flags_with_no_store(self):
        """Anonymous GET returns 200 with default flag and no-store header."""
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"allow_add_user": True}
        assert set(response.json().keys()) == {"allow_add_user"}
        assert "no-store" in response["Cache-Control"]

    def test_get_reflects_updated_allow_add_user_flag(self):
        """GET reflects saved changes to allow_add_user."""
        setting = FrontendSetting.get_solo()
        setting.allow_add_user = False
        setting.save()

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"allow_add_user": False}

    def test_get_ignores_invalid_bearer_token(self):
        """GET ignores invalid Bearer authorization headers because auth is disabled."""
        response = self.client.get(
            self.url,
            headers={"authorization": "Bearer invalid.token.value"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"allow_add_user": True}

    def test_write_methods_return_405(self):
        """POST, PUT, PATCH, and DELETE return 405 Method Not Allowed."""
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url,
                    {"allow_add_user": False},
                    format="json",
                )
                assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
