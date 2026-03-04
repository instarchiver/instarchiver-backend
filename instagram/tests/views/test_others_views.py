from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.users.tests.factories import UserFactory
from instagram.models import Story
from instagram.models import User
from instagram.tests.factories import InstagramUserFactory


class ProcessInstagramDataViewTest(TestCase):
    """Tests for the ProcessInstagramDataView endpoint."""

    def setUp(self):
        """Set up authenticated client using token authentication."""
        self.client = APIClient()
        self.url = reverse("instagram:process_data")
        self.django_user = UserFactory()
        self.token, _ = Token.objects.get_or_create(user=self.django_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")
        self.valid_payload = {
            "username": "injectuser",
            "story_id": "inject_story_001",
            "thumbnail": "https://example.com/thumb.jpg",
            "media": "https://example.com/media.mp4",
            "created_datetime": "2024-01-15T10:00:00Z",
        }

    def test_unauthenticated_request_rejected(self):
        """Test that unauthenticated requests are rejected."""
        unauthenticated_client = APIClient()
        response = unauthenticated_client.post(
            self.url,
            self.valid_payload,
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @patch("instagram.signals.story.download_file_from_url")
    def test_create_success(self, mock_download):
        """Test successful data injection creates user and story."""
        mock_download.return_value = (None, None)
        response = self.client.post(self.url, self.valid_payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["username"] == "injectuser"
        assert response.data["story_id"] == "inject_story_001"
        assert response.data["user_created"] is True
        assert response.data["story_created"] is True
        assert User.objects.filter(username="injectuser").exists()
        assert Story.objects.filter(story_id="inject_story_001").exists()

    @patch("instagram.signals.story.download_file_from_url")
    def test_existing_user_not_duplicated(self, mock_download):
        """Test that an existing user is reused without creating a duplicate."""
        mock_download.return_value = (None, None)
        InstagramUserFactory(username="existinguser")
        payload = dict(
            self.valid_payload,
            username="existinguser",
            story_id="new_story_002",
        )
        response = self.client.post(self.url, payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["user_created"] is False
        assert User.objects.filter(username="existinguser").count() == 1

    @patch("instagram.signals.story.download_file_from_url")
    def test_existing_story_not_duplicated(self, mock_download):
        """Test that an existing story_id does not create a duplicate."""
        mock_download.return_value = (None, None)
        # First injection
        self.client.post(self.url, self.valid_payload, format="json")
        # Second injection with same story_id
        response = self.client.post(self.url, self.valid_payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["story_created"] is False
        assert Story.objects.filter(story_id="inject_story_001").count() == 1

    def test_missing_required_fields_returns_400(self):
        """Test that missing required fields return a 400 error."""
        incomplete_payload = {"username": "testuser"}
        response = self.client.post(self.url, incomplete_payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_url_field_returns_400(self):
        """Test that invalid URL fields return a 400 error."""
        payload = dict(self.valid_payload, thumbnail="not-a-url")
        response = self.client.post(self.url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_datetime_returns_400(self):
        """Test that invalid datetime field returns a 400 error."""
        payload = dict(self.valid_payload, created_datetime="not-a-datetime")
        response = self.client.post(self.url, payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("instagram.signals.story.download_file_from_url")
    def test_response_contains_expected_fields(self, mock_download):
        """Test that the response contains all expected fields."""
        mock_download.return_value = (None, None)
        response = self.client.post(self.url, self.valid_payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        expected_keys = {
            "message",
            "user_created",
            "story_created",
            "username",
            "story_id",
            "thumbnail_url",
            "media_url",
            "processed_at",
        }
        assert expected_keys.issubset(set(response.data.keys()))
