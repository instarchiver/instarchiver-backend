from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from api_logs.models import APIRequestLog
from core.utils import saveapi
from settings.models import CoreAPISetting


def _mock_response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = json_data or {}
    if status_code >= 400:  # noqa: PLR2004
        error = requests.HTTPError(f"{status_code} Client Error")
        error.response = response
        response.raise_for_status.side_effect = error
    return response


class TestSaveAPISession(TestCase):
    def setUp(self):
        setting = CoreAPISetting.get_solo()
        setting.saveapi_url = "https://api.saveapi.org"
        setting.saveapi_api_key = "sk_live_test"
        setting.save()

    def test_session_uses_bearer_token(self):
        session = saveapi.get_saveapi_session()
        assert session.headers["Authorization"] == "Bearer sk_live_test"

    def test_missing_api_key_raises(self):
        setting = CoreAPISetting.get_solo()
        setting.saveapi_api_key = ""
        setting.save()

        with pytest.raises(ImproperlyConfigured):
            saveapi.get_saveapi_session()

    def test_missing_url_raises(self):
        setting = CoreAPISetting.get_solo()
        setting.saveapi_url = ""
        setting.save()

        with pytest.raises(ImproperlyConfigured):
            saveapi.get_saveapi_url()


class TestSaveAPIDownload(TestCase):
    def setUp(self):
        setting = CoreAPISetting.get_solo()
        setting.saveapi_url = "https://api.saveapi.org/"
        setting.saveapi_api_key = "sk_live_test"
        setting.save()

    @patch("requests.Session.request")
    def test_download_sends_url_param_and_logs(self, mock_request):
        mock_request.return_value = _mock_response(json_data={"success": True})

        result = saveapi.download("https://www.instagram.com/stories/someone/")

        assert result == {"success": True}
        kwargs = mock_request.call_args.kwargs
        assert kwargs["method"] == "GET"
        assert kwargs["url"] == "https://api.saveapi.org/v1/download"
        assert kwargs["params"] == {
            "url": "https://www.instagram.com/stories/someone/",
        }

        log = APIRequestLog.objects.get()
        assert log.url == "https://api.saveapi.org/v1/download"
        assert log.status == APIRequestLog.STATUS_SUCCESS
        assert log.response_status_code == 200  # noqa: PLR2004

    @patch("requests.Session.request")
    def test_download_http_error_is_logged_and_raised(self, mock_request):
        mock_request.return_value = _mock_response(
            status_code=429,
            json_data={"success": False, "error": {"code": "RATE_LIMITED"}},
        )

        with pytest.raises(requests.HTTPError, match="429"):
            saveapi.download("https://www.instagram.com/stories/someone/")

        log = APIRequestLog.objects.get()
        assert log.status == APIRequestLog.STATUS_ERROR
        assert log.response_status_code == 429  # noqa: PLR2004

    @patch("core.utils.saveapi.download")
    def test_fetch_user_stories_builds_story_url(self, mock_download):
        mock_download.return_value = {"success": True, "medias": []}

        saveapi.fetch_user_stories("someone")

        mock_download.assert_called_once_with(
            "https://www.instagram.com/stories/someone/",
        )
