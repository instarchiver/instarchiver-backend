from unittest.mock import patch

import pytest
from django.test import TestCase

from core.utils.saveapi import SaveAPIError
from instagram.models import Story
from instagram.models import User
from instagram.models.story import UserUpdateStoryLog
from instagram.tests.factories import InstagramUserFactory


class TestUserModelStr(TestCase):
    """Tests for the User.__str__ method."""

    def test_str_returns_username(self):
        """Test that the string representation is the username."""
        user = InstagramUserFactory(username="strtest")
        assert str(user) == "strtest"


class TestUserModelDelete(TestCase):
    """Tests for the User.delete method."""

    def test_delete_removes_user(self):
        """Test that deleting a user removes it from the database."""
        user = InstagramUserFactory()
        user_uuid = user.uuid
        user.delete()
        assert not User.objects.filter(uuid=user_uuid).exists()

    def test_delete_clears_history(self):
        """Test that deleting a user also removes historical records."""
        user = InstagramUserFactory()
        # Save to create history entry
        user.biography = "Updated bio"
        user.save()
        assert user.history.count() > 0
        user.delete()
        # Historical records for this uuid should be gone
        assert User.history.filter(uuid=user.uuid).count() == 0


def _saveapi_profile(**overrides):
    data = {
        "success": True,
        "platform": "instagram",
        "id": "111",
        "username": "testuser",
        "full_name": "Updated Name",
        "biography": "Updated bio",
        "followers": 5000,
        "following": 300,
        "posts": 100,
        "is_private": False,
        "is_verified": True,
        "profile_pic_url": "https://example.com/pic.jpg",
        "profile_pic_url_hd": "https://example.com/pic_hd.jpg",
        "recent_posts": [{"id": "1", "shortcode": "abc"}],
        "credits": {"spent": 3, "remaining": 242},
    }
    data.update(overrides)
    return data


class TestUserExtractApiData(TestCase):
    """Tests for the User._extract_api_data_from_saveapi method."""

    def test_extract_populates_fields(self):
        """Every mapped SaveAPI key ends up on the matching model field."""
        user = InstagramUserFactory()
        user._extract_api_data_from_saveapi(  # noqa: SLF001
            _saveapi_profile(id="123456789", username="newusername", is_private=True),
        )
        assert user.instagram_id == "123456789"
        assert user.username == "newusername"
        assert user.full_name == "Updated Name"
        assert user.original_profile_picture_url == "https://example.com/pic_hd.jpg"
        assert user.biography == "Updated bio"
        assert user.is_private is True
        assert user.is_verified is True
        assert user.media_count == 100  # noqa: PLR2004
        assert user.follower_count == 5000  # noqa: PLR2004
        assert user.following_count == 300  # noqa: PLR2004

    def test_extract_falls_back_to_standard_profile_pic(self):
        """profile_pic_url is used when the HD URL is missing."""
        user = InstagramUserFactory()
        user._extract_api_data_from_saveapi(  # noqa: SLF001
            _saveapi_profile(profile_pic_url_hd=None),
        )
        assert user.original_profile_picture_url == "https://example.com/pic.jpg"

    def test_extract_handles_null_values(self):
        """Null values become empty strings, zeros, False or the stored id."""
        user = InstagramUserFactory(instagram_id="555")
        user._extract_api_data_from_saveapi(  # noqa: SLF001
            _saveapi_profile(
                id=None,
                full_name=None,
                biography=None,
                followers=None,
                following=None,
                posts=None,
                is_private=None,
                is_verified=None,
                profile_pic_url=None,
                profile_pic_url_hd=None,
            ),
        )
        assert user.instagram_id == "555"
        assert user.full_name == ""
        assert user.biography == ""
        assert user.follower_count == 0
        assert user.following_count == 0
        assert user.media_count == 0
        assert user.is_private is False
        assert user.is_verified is False
        assert user.original_profile_picture_url == ""

    def test_extract_none_data_is_noop(self):
        """Passing None leaves the user unchanged."""
        user = InstagramUserFactory(username="unchanged")
        user._extract_api_data_from_saveapi(None)  # noqa: SLF001
        assert user.username == "unchanged"


class TestUserUpdateProfileFromApi(TestCase):
    """Tests for the User.update_profile_from_api method."""

    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_success(self, mock_fetch):
        """A successful response updates and saves the profile."""
        user = InstagramUserFactory(username="testuser", instagram_id="111")
        mock_fetch.return_value = _saveapi_profile()

        user.update_profile_from_api()

        mock_fetch.assert_called_once_with("testuser")
        user.refresh_from_db()
        assert user.full_name == "Updated Name"
        assert user.follower_count == 5000  # noqa: PLR2004
        assert user.api_updated_at is not None
        assert "credits" not in user.raw_api_data
        assert "recent_posts" not in user.raw_api_data
        assert user.raw_api_data["id"] == "111"

    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_sets_missing_instagram_id(self, mock_fetch):
        """A user without an Instagram id gets the one SaveAPI returns."""
        user = InstagramUserFactory(username="testuser", instagram_id=None)
        mock_fetch.return_value = _saveapi_profile(id="4060475001")

        user.update_profile_from_api()

        user.refresh_from_db()
        assert user.instagram_id == "4060475001"

    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_raises_when_not_successful(self, mock_fetch):
        """success: false raises a SaveAPIError and saves nothing."""
        user = InstagramUserFactory(username="erroruser", full_name="Old")
        mock_fetch.return_value = {
            "success": False,
            "error": {"code": "NOT_FOUND", "message": "User not found"},
        }

        with pytest.raises(SaveAPIError, match="User not found") as exc_info:
            user.update_profile_from_api()

        assert exc_info.value.code == "NOT_FOUND"
        assert exc_info.value.retryable is False
        user.refresh_from_db()
        assert user.full_name == "Old"
        assert user.api_updated_at is None

    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_rate_limited_is_retryable(self, mock_fetch):
        """A RATE_LIMITED error in the body is marked retryable."""
        user = InstagramUserFactory(username="testuser")
        mock_fetch.return_value = {
            "success": False,
            "error": {"code": "RATE_LIMITED", "message": "Slow down"},
        }

        with pytest.raises(SaveAPIError) as exc_info:
            user.update_profile_from_api()

        assert exc_info.value.retryable is True

    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_rejects_id_mismatch(self, mock_fetch):
        """A username that now belongs to another account is not saved over."""
        user = InstagramUserFactory(
            username="testuser",
            instagram_id="111",
            full_name="Original Owner",
        )
        mock_fetch.return_value = _saveapi_profile(id="999", full_name="New Owner")

        with pytest.raises(SaveAPIError) as exc_info:
            user.update_profile_from_api()

        assert exc_info.value.code == "ID_MISMATCH"
        assert exc_info.value.retryable is False
        user.refresh_from_db()
        assert user.full_name == "Original Owner"

    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_rejects_id_stored_on_another_user(self, mock_fetch):
        """An Instagram id already stored on another row is not saved."""
        InstagramUserFactory(username="olduser", instagram_id="111")
        user = InstagramUserFactory(username="testuser", instagram_id=None)
        mock_fetch.return_value = _saveapi_profile(id="111")

        with pytest.raises(SaveAPIError) as exc_info:
            user.update_profile_from_api()

        assert exc_info.value.code == "DUPLICATE_ACCOUNT"
        user.refresh_from_db()
        assert user.instagram_id is None

    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_rejects_username_stored_on_another_user(
        self,
        mock_fetch,
    ):
        """A returned username already stored on another row is not saved."""
        InstagramUserFactory(username="someone", instagram_id="222")
        user = InstagramUserFactory(username="Someone", instagram_id=None)
        mock_fetch.return_value = _saveapi_profile(id="333", username="someone")

        with pytest.raises(SaveAPIError) as exc_info:
            user.update_profile_from_api()

        assert exc_info.value.code == "DUPLICATE_ACCOUNT"


SAVEAPI_IMAGE_URL = (
    "https://scontent.cdninstagram.com/v/t51/111_222_333_n.webp?oh=abc&oe=1"
)
SAVEAPI_VIDEO_URL = (
    "https://scontent.cdninstagram.com/o1/v/t2/f2/m78/AQN_video.mp4?oh=abc"
)


class TestUserUpdateStoriesFromSaveApi(TestCase):
    """Tests for GetUserStoryMixIn on the User model."""

    def _response(self, *medias):
        return {"success": True, "type": "album", "medias": list(medias)}

    @patch("instagram.models.user.fetch_user_stories_from_saveapi")
    def test_creates_image_and_video_stories(self, mock_fetch):
        """Image stories keep the URL as thumbnail; video stories get none."""
        user = InstagramUserFactory(username="saveapiuser")
        mock_fetch.return_value = self._response(
            {"type": "image", "url": SAVEAPI_IMAGE_URL, "ext": "webp"},
            {"type": "video", "url": SAVEAPI_VIDEO_URL, "ext": "mp4"},
        )

        updated = user.update_stories_from_saveapi()

        assert len(updated) == 2  # noqa: PLR2004
        image_story, video_story = updated
        assert image_story.thumbnail_url == SAVEAPI_IMAGE_URL
        assert image_story.media_url == SAVEAPI_IMAGE_URL
        assert video_story.thumbnail_url == ""
        assert video_story.media_url == SAVEAPI_VIDEO_URL
        assert len(image_story.story_id) == 40  # noqa: PLR2004
        assert image_story.user == user
        assert image_story.story_created_at is not None

        log = UserUpdateStoryLog.objects.filter(user=user).first()
        assert log.status == UserUpdateStoryLog.STATUS_COMPLETED

    @patch("instagram.models.user.fetch_user_stories_from_saveapi")
    def test_story_id_ignores_query_string(self, mock_fetch):
        """The same media with new signatures maps to the same story."""
        user = InstagramUserFactory(username="stableid")
        mock_fetch.return_value = self._response(
            {"type": "image", "url": SAVEAPI_IMAGE_URL},
        )
        user.update_stories_from_saveapi()

        resigned_url = SAVEAPI_IMAGE_URL.split("?", maxsplit=1)[0] + "?oh=new"
        mock_fetch.return_value = self._response(
            {"type": "image", "url": resigned_url},
        )
        user.update_stories_from_saveapi()

        assert Story.objects.filter(user=user).count() == 1

    def test_get_story_id_from_media_url_ignores_query_string(self):
        """URLs that differ only in the query string get the same story id."""
        resigned_url = SAVEAPI_IMAGE_URL.split("?", maxsplit=1)[0] + "?oh=new"

        assert User._get_story_id_from_media_url(  # noqa: SLF001
            SAVEAPI_IMAGE_URL,
        ) == User._get_story_id_from_media_url(resigned_url)  # noqa: SLF001

    @patch("instagram.models.user.fetch_user_stories_from_saveapi")
    def test_skips_media_without_url(self, mock_fetch):
        """Media entries without a URL are ignored."""
        user = InstagramUserFactory(username="nourl")
        mock_fetch.return_value = self._response({"type": "image", "url": None})

        assert user.update_stories_from_saveapi() == []

    @patch("instagram.models.user.fetch_user_stories_from_saveapi")
    def test_unsuccessful_response_sets_log_failed(self, mock_fetch):
        """A success=false response fails the log and raises."""
        user = InstagramUserFactory(username="failsave")
        mock_fetch.return_value = {
            "success": False,
            "error": {"code": "INVALID_URL", "message": "Bad link"},
        }

        with pytest.raises(SaveAPIError, match="INVALID_URL: Bad link") as exc_info:
            user.update_stories_from_saveapi()

        assert exc_info.value.code == "INVALID_URL"
        assert exc_info.value.retryable is False

        log = UserUpdateStoryLog.objects.filter(user=user).first()
        assert log.status == UserUpdateStoryLog.STATUS_FAILED
        assert "INVALID_URL" in log.message

    @patch("instagram.models.user.fetch_user_stories_from_saveapi")
    def test_request_exception_sets_log_failed(self, mock_fetch):
        """An exception from the client fails the log and is re-raised."""
        user = InstagramUserFactory(username="raisesave")
        mock_fetch.side_effect = RuntimeError("Connection reset")

        with pytest.raises(RuntimeError):
            user.update_stories_from_saveapi()

        log = UserUpdateStoryLog.objects.filter(user=user).first()
        assert log.status == UserUpdateStoryLog.STATUS_FAILED
        assert "Connection reset" in log.message

    @patch("instagram.tasks.update_user_stories_from_saveapi.delay")
    def test_async_queues_task(self, mock_delay):
        """update_stories_from_saveapi_async queues the Celery task."""
        user = InstagramUserFactory()
        user.update_stories_from_saveapi_async()
        mock_delay.assert_called_once_with(user.uuid)
