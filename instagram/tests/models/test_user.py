from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import TestCase

from instagram.models import Story
from instagram.models import User
from instagram.models.story import UserUpdateStoryLog
from instagram.tests.factories import InstagramUserFactory
from instagram.tests.factories import StoryFactory


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


class TestUserExtractApiData(TestCase):
    """Tests for the User._extract_api_data_* methods."""

    def test_extract_api_data_from_username_v2_basic(self):
        """Test that _extract_api_data_from_username_v2 populates fields correctly."""
        user = InstagramUserFactory()
        data = {
            "id": "123456789",
            "username": "newusername",
            "full_name": "New Name",
            "profile_pic_url_hd": "https://example.com/pic_hd.jpg",
            "profile_pic_url": "https://example.com/pic.jpg",
            "biography": "Test bio",
            "is_private": True,
            "is_verified": False,
            "edge_owner_to_timeline_media": {"count": 50},
            "edge_followed_by": {"count": 1000},
            "edge_follow": {"count": 200},
        }
        user._extract_api_data_from_username_v2(data)  # noqa: SLF001
        assert user.instagram_id == "123456789"
        assert user.username == "newusername"
        assert user.full_name == "New Name"
        assert user.original_profile_picture_url == "https://example.com/pic_hd.jpg"
        assert user.biography == "Test bio"
        assert user.is_private is True
        assert user.is_verified is False
        assert user.media_count == 50  # noqa: PLR2004
        assert user.follower_count == 1000  # noqa: PLR2004
        assert user.following_count == 200  # noqa: PLR2004

    def test_extract_api_data_from_username_v2_fallback_profile_pic(self):
        """Test that profile_pic_url is used as fallback when hd URL is absent."""
        user = InstagramUserFactory()
        data = {
            "id": "111",
            "username": "user",
            "profile_pic_url": "https://example.com/pic.jpg",
        }
        user._extract_api_data_from_username_v2(data)  # noqa: SLF001
        assert user.original_profile_picture_url == "https://example.com/pic.jpg"

    def test_extract_api_data_from_username_v2_none_data(self):
        """Test that passing None data is a no-op."""
        user = InstagramUserFactory(username="unchanged")
        user._extract_api_data_from_username_v2(None)  # noqa: SLF001
        assert user.username == "unchanged"

    def test_extract_api_data_from_user_id_basic(self):
        """Test that _extract_api_data_from_user_id populates fields correctly."""
        user = InstagramUserFactory()
        data = {
            "id": "987654321",
            "username": "byid_user",
            "full_name": "By ID Name",
            "profile_pic_url_hd": "https://example.com/hd.jpg",
            "biography": "Bio by id",
            "is_private": False,
            "is_verified": True,
            "edge_owner_to_timeline_media": {"count": 10},
            "edge_followed_by": {"count": 500},
            "edge_follow": {"count": 100},
        }
        user._extract_api_data_from_user_id(data)  # noqa: SLF001
        assert user.instagram_id == "987654321"
        assert user.username == "byid_user"
        assert user.full_name == "By ID Name"
        assert user.is_verified is True
        assert user.media_count == 10  # noqa: PLR2004
        assert user.follower_count == 500  # noqa: PLR2004
        assert user.following_count == 100  # noqa: PLR2004

    def test_extract_api_data_from_user_id_none_data(self):
        """Test that passing None data is a no-op."""
        user = InstagramUserFactory(username="unchanged_id")
        user._extract_api_data_from_user_id(None)  # noqa: SLF001
        assert user.username == "unchanged_id"


class TestUserUpdateProfileFromApi(TestCase):
    """Tests for the User.update_profile_from_api method."""

    @patch("instagram.models.user.fetch_user_info_by_username_v2")
    def test_update_profile_from_api_success_username_v2(self, mock_fetch):
        """Test successful profile update via username v2 API."""
        user = InstagramUserFactory(username="testuser", instagram_id="111")
        mock_fetch.return_value = {
            "data": {
                "status": True,
                "data": {
                    "user": {
                        "id": "111",
                        "username": "testuser",
                        "full_name": "Updated Name",
                        "profile_pic_url_hd": "https://example.com/pic.jpg",
                        "biography": "Updated bio",
                        "is_private": False,
                        "is_verified": True,
                        "edge_owner_to_timeline_media": {"count": 100},
                        "edge_followed_by": {"count": 5000},
                        "edge_follow": {"count": 300},
                    },
                },
            },
        }
        user.update_profile_from_api()
        user.refresh_from_db()
        assert user.full_name == "Updated Name"
        assert user.api_updated_at is not None

    @patch("instagram.models.user.fetch_user_info_by_user_id")
    @patch("instagram.models.user.fetch_user_info_by_username_v2")
    def test_update_profile_falls_back_to_user_id(
        self,
        mock_fetch_username,
        mock_fetch_id,
    ):
        """Test that update_profile_from_api falls back to user_id API on failure."""
        user = InstagramUserFactory(username="fallback_user", instagram_id="222")
        # Username v2 returns status=False so falls back
        mock_fetch_username.return_value = {
            "data": {"status": False, "errorMessage": "Not found"},
        }
        mock_fetch_id.return_value = {
            "data": {
                "status": True,
                "id": "222",
                "username": "fallback_user",
                "full_name": "Fallback Name",
                "profile_pic_url_hd": "",
                "profile_pic_url": "",
                "biography": "",
                "is_private": False,
                "is_verified": False,
                "edge_owner_to_timeline_media": {"count": 0},
                "edge_followed_by": {"count": 0},
                "edge_follow": {"count": 0},
            },
        }
        user.update_profile_from_api()
        user.refresh_from_db()
        assert user.api_updated_at is not None

    @patch("instagram.models.user.fetch_user_info_by_user_id")
    @patch("instagram.models.user.fetch_user_info_by_username_v2")
    def test_update_profile_user_id_api_also_fails(
        self,
        mock_fetch_username,
        mock_fetch_id,
    ):
        """Test error raised when user_id API also returns failure (lines 274-279)."""
        user = InstagramUserFactory(username="dualfail_user", instagram_id="999")
        # Username v2 fails → fallback to user_id
        mock_fetch_username.return_value = {
            "data": {"status": False, "errorMessage": "v2 not found"},
        }
        # user_id API also fails
        mock_fetch_id.return_value = {
            "data": {"status": False, "errorMessage": "user_id also failed"},
        }
        with pytest.raises(Exception, match="user_id also failed"):
            user.update_profile_from_api()

    @patch("instagram.models.user.fetch_user_info_by_username_v2")
    def test_update_profile_raises_on_api_error(self, mock_fetch):
        """Test that update_profile_from_api raises on API error without fallback."""
        # User has no instagram_id so the user_id fallback is skipped
        user = InstagramUserFactory(username="erroruser", instagram_id=None)
        mock_fetch.return_value = {
            "data": {"status": False, "errorMessage": "User not found"},
        }
        with pytest.raises(Exception, match="User not found"):
            user.update_profile_from_api()


class TestUserGetPostDataFromApi(TestCase):
    """Tests for the GetUserPostMixIn methods."""

    @patch("instagram.models.user.fetch_user_posts_by_username")
    def test_get_post_data_from_api_success(self, mock_fetch):
        """Test successful post data retrieval from API."""
        user = InstagramUserFactory(instagram_id="333")
        mock_fetch.return_value = {
            "data": {
                "items": [{"pk": "p1"}, {"pk": "p2"}],
                "next_max_id": None,
            },
        }
        items, next_max_id = user.get_post_data_from_api()
        assert len(items) == 2  # noqa: PLR2004
        assert next_max_id is None

    def test_get_post_data_from_api_no_instagram_id(self):
        """Test that get_post_data_from_api raises ValueError without instagram_id."""
        user = InstagramUserFactory(instagram_id=None)
        with pytest.raises(ValueError, match="has no Instagram ID"):
            user.get_post_data_from_api()

    @patch("instagram.models.user.fetch_user_posts_by_username")
    def test_update_post_data_from_api_saves_posts(self, mock_fetch):
        """Test that _update_post_data_from_api saves posts to database."""
        user = InstagramUserFactory(instagram_id="444")
        mock_fetch.return_value = {
            "data": {
                "items": [
                    {
                        "pk": "post_001",
                        "display_uri": "https://example.com/img.jpg",
                        "caption": {"text": "My caption"},
                        "taken_at": 1700000000,
                    },
                ],
                "next_max_id": None,
            },
        }
        result = user._update_post_data_from_api()  # noqa: SLF001
        assert result["total_posts"] == 1
        assert result["pages_fetched"] == 1

    @patch("instagram.models.user.fetch_user_posts_by_username")
    def test_update_post_data_from_api_pagination(self, mock_fetch):
        """Test that _update_post_data_from_api handles pagination."""
        user = InstagramUserFactory(instagram_id="555")
        mock_fetch.side_effect = [
            {
                "data": {
                    "items": [
                        {
                            "pk": "p1",
                            "display_uri": "",
                            "caption": None,
                            "taken_at": None,
                        },
                    ],
                    "next_max_id": "cursor_abc",
                },
            },
            {
                "data": {
                    "items": [
                        {
                            "pk": "p2",
                            "display_uri": "",
                            "caption": None,
                            "taken_at": None,
                        },
                    ],
                    "next_max_id": None,
                },
            },
        ]
        result = user._update_post_data_from_api()  # noqa: SLF001
        assert result["total_posts"] == 2  # noqa: PLR2004
        assert result["pages_fetched"] == 2  # noqa: PLR2004

    @patch("instagram.models.user.fetch_user_posts_by_username")
    def test_update_post_data_from_api_sync_wrapper(self, mock_fetch):
        """Test that update_post_data_from_api calls _update_post_data_from_api."""
        user = InstagramUserFactory(instagram_id="666")
        mock_fetch.return_value = {
            "data": {"items": [], "next_max_id": None},
        }
        # Should not raise
        user.update_post_data_from_api()

    @patch("instagram.tasks.update_user_posts_from_api.delay")
    def test_update_posts_from_api_async(self, mock_delay):
        """Test that update_posts_from_api_async queues a Celery task."""
        user = InstagramUserFactory()
        mock_result = MagicMock()
        mock_result.id = "task-001"
        mock_delay.return_value = mock_result
        user.update_posts_from_api_async()
        mock_delay.assert_called_once_with(user.uuid)


class TestUserUpdateStoriesFromApi(TestCase):
    """Tests for User._update_stories_from_api and related methods."""

    @patch("instagram.models.user.fetch_user_stories_by_username")
    def test_update_stories_from_api_success(self, mock_fetch):
        """Test successful story update from API."""
        user = InstagramUserFactory(username="storyuser")
        mock_fetch.return_value = {
            "code": 200,
            "data": {
                "data": {
                    "items": [
                        {
                            "id": "story_001",
                            "thumbnail_url": "https://example.com/thumb.jpg",
                            "video_url": "https://example.com/video.mp4",
                            "taken_at_date": "2024-01-01T00:00:00Z",
                        },
                    ],
                },
            },
        }
        updated = user._update_stories_from_api()  # noqa: SLF001
        assert len(updated) == 1
        assert Story.objects.filter(story_id="story_001").exists()

        # Check a log entry was created with COMPLETED status
        log = UserUpdateStoryLog.objects.filter(user=user).first()
        assert log is not None
        assert log.status == UserUpdateStoryLog.STATUS_COMPLETED

    @patch("instagram.models.user.fetch_user_stories_by_username")
    def test_update_stories_from_api_api_error(self, mock_fetch):
        """Test that an API error updates log with FAILED status and raises."""
        user = InstagramUserFactory(username="erruser")
        mock_fetch.return_value = {
            "code": 400,
            "message": "Rate limited",
        }
        with pytest.raises(Exception, match="Rate limited"):
            user._update_stories_from_api()  # noqa: SLF001

        log = UserUpdateStoryLog.objects.filter(user=user).first()
        assert log is not None
        assert log.status == UserUpdateStoryLog.STATUS_FAILED

    @patch("instagram.models.user.fetch_user_stories_by_username")
    def test_update_stories_from_api_sync_wrapper(self, mock_fetch):
        """Test that update_stories_from_api delegates to _update_stories_from_api."""
        user = InstagramUserFactory(username="syncuser")
        mock_fetch.return_value = {
            "code": 200,
            "data": {"data": {"items": []}},
        }
        result = user.update_stories_from_api()
        assert isinstance(result, list)

    @patch("instagram.tasks.update_user_stories_from_api.delay")
    def test_update_stories_from_api_async(self, mock_delay):
        """Test that update_stories_from_api_async queues a Celery task."""
        user = InstagramUserFactory()
        mock_result = MagicMock()
        mock_result.id = "task-002"
        mock_delay.return_value = mock_result
        user.update_stories_from_api_async()
        mock_delay.assert_called_once_with(user.uuid)

    @patch("instagram.models.user.fetch_user_stories_by_username")
    def test_update_stories_exception_sets_log_failed(self, mock_fetch):
        """Test that an unexpected exception sets log status to FAILED."""
        user = InstagramUserFactory(username="raiseuser")
        # Raise an actual exception (not a bad response code) so the log is
        # still STATUS_IN_PROGRESS when the except block runs.
        mock_fetch.side_effect = RuntimeError("Unexpected connection error")
        with pytest.raises(RuntimeError):
            user._update_stories_from_api()  # noqa: SLF001

        log = UserUpdateStoryLog.objects.filter(user=user).first()
        assert log is not None
        assert log.status == UserUpdateStoryLog.STATUS_FAILED
        assert "Unexpected connection error" in log.message

    @patch("instagram.models.user.fetch_user_stories_by_username")
    @patch("instagram.signals.story.download_file_from_url")
    def test_update_stories_existing_story_not_duplicated(
        self,
        mock_download,
        mock_fetch,
    ):
        """Test that existing stories are not duplicated on re-update."""
        mock_download.return_value = (None, None)
        user = InstagramUserFactory(username="nodupuser")
        StoryFactory(story_id="existing_story", user=user)
        mock_fetch.return_value = {
            "code": 200,
            "data": {
                "data": {
                    "items": [
                        {
                            "id": "existing_story",
                            "thumbnail_url": "https://example.com/t.jpg",
                            "video_url": None,
                            "taken_at_date": "2024-01-01T00:00:00Z",
                        },
                    ],
                },
            },
        }
        user._update_stories_from_api()  # noqa: SLF001
        assert Story.objects.filter(story_id="existing_story").count() == 1
