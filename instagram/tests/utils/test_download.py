from unittest.mock import Mock
from unittest.mock import patch

import requests
from django.test import TestCase

from instagram.utils import download_file_from_url


class TestDownloadFileFromUrl(TestCase):
    """Tests for the download_file_from_url utility function."""

    @patch("instagram.utils.requests.get")
    def test_download_success_jpg_extension(self, mock_get):
        """Test successful download with a .jpg URL."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"image_bytes"
        mock_response.headers = {}
        mock_get.return_value = mock_response

        content, ext = download_file_from_url("https://example.com/photo.jpg")
        assert content == b"image_bytes"
        assert ext == "jpg"

    @patch("instagram.utils.requests.get")
    def test_download_success_mp4_extension(self, mock_get):
        """Test successful download with a .mp4 URL."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"video_bytes"
        mock_response.headers = {}
        mock_get.return_value = mock_response

        content, ext = download_file_from_url("https://example.com/video.mp4")
        assert content == b"video_bytes"
        assert ext == "mp4"

    @patch("instagram.utils.requests.get")
    def test_download_uses_content_type_for_extension_when_no_dot(self, mock_get):
        """Test extension detection from content-type when URL has no dot."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"image_bytes"
        mock_response.headers = {"content-type": "image/jpeg"}
        mock_get.return_value = mock_response

        content, ext = download_file_from_url("https://example.com/photo")
        assert content == b"image_bytes"
        assert ext == "jpg"

    @patch("instagram.utils.requests.get")
    def test_download_uses_video_content_type(self, mock_get):
        """Test extension detection from video content-type."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"video_bytes"
        mock_response.headers = {"content-type": "video/mp4"}
        mock_get.return_value = mock_response

        content, ext = download_file_from_url("https://example.com/stream")
        assert content == b"video_bytes"
        assert ext == "mp4"

    @patch("instagram.utils.requests.get")
    def test_download_returns_none_on_non_200_status(self, mock_get):
        """Test that a non-200 HTTP response returns (None, None)."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        content, ext = download_file_from_url("https://example.com/missing.jpg")
        assert content is None
        assert ext is None

    @patch("instagram.utils.requests.get")
    def test_download_returns_none_on_exception(self, mock_get):
        """Test that a network exception returns (None, None) gracefully."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Down")

        content, ext = download_file_from_url("https://example.com/photo.jpg")
        assert content is None
        assert ext is None

    @patch("instagram.utils.requests.get")
    def test_download_fallback_extension_bin(self, mock_get):
        """Test fallback extension 'bin' when content-type is unknown."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b"binary_data"
        mock_response.headers = {"content-type": "application/octet-stream"}
        mock_get.return_value = mock_response

        content, ext = download_file_from_url("https://example.com/data")
        assert content == b"binary_data"
        assert ext == "bin"
