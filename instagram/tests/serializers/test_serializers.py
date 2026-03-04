from unittest.mock import patch

from django.test import TestCase

from instagram.serializers.users import CreateInstagramUserStoryCreditSerializer
from instagram.serializers.users import InstagramUserCreateSerializer
from instagram.serializers.users import InstagramUserHistoryListSerializer
from instagram.tests.factories import InstagramUserFactory


class TestInstagramUserCreateSerializer(TestCase):
    """Tests for the InstagramUserCreateSerializer."""

    def test_validate_username_raises_if_already_exists(self):
        """Test that validate_username raises ValidationError for duplicate username."""
        InstagramUserFactory(username="existinguser")
        serializer = InstagramUserCreateSerializer(data={"username": "existinguser"})
        assert not serializer.is_valid()
        assert "username" in serializer.errors

    def test_validate_username_passes_for_new_username(self):
        """Test that validate_username passes for a brand-new username."""
        serializer = InstagramUserCreateSerializer(data={"username": "brandnewuser"})
        # is_valid() calls validate_username; data is valid at this stage
        assert serializer.is_valid()

    @patch("instagram.serializers.users.InstagramUser.update_profile_from_api")
    def test_create_calls_update_profile_from_api(self, mock_update):
        """Test that create() calls update_profile_from_api on the new user."""
        serializer = InstagramUserCreateSerializer(data={"username": "newuser123"})
        assert serializer.is_valid()
        serializer.save()
        mock_update.assert_called_once()


class TestInstagramUserHistoryListSerializer(TestCase):
    """Tests for the InstagramUserHistoryListSerializer.get_profile_picture."""

    def test_get_profile_picture_returns_none_when_empty(self):
        """Test that get_profile_picture returns None when no profile picture."""
        user = InstagramUserFactory(original_profile_picture_url="")
        # Access the history record
        history_record = user.history.first()
        serializer = InstagramUserHistoryListSerializer(history_record)
        assert serializer.data["profile_picture"] is None

    @patch("instagram.serializers.users.default_storage")
    def test_get_profile_picture_returns_url_when_set(self, mock_storage):
        """Test that get_profile_picture returns a URL when profile picture is set."""
        mock_storage.url.return_value = "https://example.com/storage/pic.jpg"
        user = InstagramUserFactory(original_profile_picture_url="")
        history_record = user.history.first()
        # Manually set the profile_picture on the history object to simulate a saved pic
        history_record.profile_picture = "users/testuser/pic.jpg"
        serializer = InstagramUserHistoryListSerializer(history_record)
        assert (
            serializer.data["profile_picture"] == "https://example.com/storage/pic.jpg"
        )
        mock_storage.url.assert_called_once_with("users/testuser/pic.jpg")


class TestCreateInstagramUserStoryCreditSerializer(TestCase):
    """Tests for the CreateInstagramUserStoryCreditSerializer."""

    def test_valid_positive_credit(self):
        """Test that a valid positive credit value passes validation."""
        serializer = CreateInstagramUserStoryCreditSerializer(data={"story_credit": 10})
        assert serializer.is_valid()
        assert serializer.validated_data["story_credit"] == 10  # noqa: PLR2004

    def test_zero_credit_is_valid(self):
        """Test that zero credit value is valid."""
        serializer = CreateInstagramUserStoryCreditSerializer(data={"story_credit": 0})
        assert serializer.is_valid()

    def test_negative_credit_raises_validation_error(self):
        """Test that a negative credit value fails validation."""
        serializer = CreateInstagramUserStoryCreditSerializer(
            data={"story_credit": -5},
        )
        assert not serializer.is_valid()
        assert "story_credit" in serializer.errors
