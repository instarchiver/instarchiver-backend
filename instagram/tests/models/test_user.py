from datetime import UTC
from datetime import datetime
from unittest.mock import patch

import pytest
import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from core.utils.saveapi import SaveAPIError
from instagram.models import Post
from instagram.models import Story
from instagram.models import User
from instagram.models.story import UserUpdateStoryLog
from instagram.tests.factories import InstagramUserFactory
from instagram.tests.factories import PostFactory


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


class TestUserGetPostUrls(TestCase):
    """Tests for the User.get_post_urls method."""

    def test_returns_url_id_and_shortcode(self):
        """Each recent post comes back with only url, id and shortcode."""
        user = InstagramUserFactory(
            raw_api_data={
                "recent_posts": [
                    {
                        "id": "4026662792306603741",
                        "shortcode": "DfhlHm1t7bd",
                        "url": "https://www.instagram.com/p/DfhlHm1t7bd/",
                        "type": "video",
                        "likes": 1299,
                    },
                    {
                        "id": "4026631408862937765",
                        "shortcode": "Dfhd-6utMKl",
                        "url": "https://www.instagram.com/p/Dfhd-6utMKl/",
                        "type": "image",
                    },
                ],
            },
        )
        assert user.get_post_urls() == [
            {
                "url": "https://www.instagram.com/p/DfhlHm1t7bd/",
                "id": "4026662792306603741",
                "shortcode": "DfhlHm1t7bd",
            },
            {
                "url": "https://www.instagram.com/p/Dfhd-6utMKl/",
                "id": "4026631408862937765",
                "shortcode": "Dfhd-6utMKl",
            },
        ]

    def test_empty_when_raw_api_data_is_none(self):
        """No raw data means no posts."""
        user = InstagramUserFactory(raw_api_data=None)
        assert user.get_post_urls() == []

    def test_empty_when_recent_posts_is_not_a_list(self):
        """A missing, null or non-list recent_posts returns an empty list."""
        for raw in ({}, {"recent_posts": None}, {"recent_posts": {"id": "1"}}):
            user = InstagramUserFactory(raw_api_data=raw)
            assert user.get_post_urls() == []

    def test_skips_non_dict_items_and_keeps_missing_keys_as_none(self):
        """Non-dict items are skipped and a missing key comes back as None."""
        user = InstagramUserFactory(
            raw_api_data={"recent_posts": ["junk", None, {"id": "1"}]},
        )
        assert user.get_post_urls() == [{"url": None, "id": "1", "shortcode": None}]


def _recent_posts(*urls):
    return {
        "recent_posts": [
            {"id": str(i), "shortcode": f"code{i}", "url": url}
            for i, url in enumerate(urls)
        ],
    }


@patch("instagram.models.user.fetch_post_detail")
class TestUserFetchPostDetails(TestCase):
    """Tests for the User.fetch_post_details method."""

    def test_returns_response_for_each_post(self, mock_fetch):
        """Each post url is fetched and its response returned in order."""
        user = InstagramUserFactory(raw_api_data=_recent_posts("u1", "u2"))
        mock_fetch.side_effect = [
            {"success": True, "id": "a"},
            {"success": True, "id": "b"},
        ]

        assert list(user.fetch_post_details()) == [
            {"success": True, "id": "a"},
            {"success": True, "id": "b"},
        ]
        assert [c.args[0] for c in mock_fetch.call_args_list] == ["u1", "u2"]

    def test_post_without_url_is_not_fetched(self, mock_fetch):
        """A post with no url never reaches SaveAPI."""
        user = InstagramUserFactory(raw_api_data={"recent_posts": [{"id": "1"}]})

        assert list(user.fetch_post_details()) == []
        mock_fetch.assert_not_called()

    def test_failed_posts_are_skipped(self, mock_fetch):
        """Error bodies, non-dict bodies, SaveAPI errors and timeouts are skipped."""
        user = InstagramUserFactory(
            raw_api_data=_recent_posts("u1", "u2", "u3", "u4", "u5"),
        )
        mock_fetch.side_effect = [
            {"success": False, "error": {"code": "NOT_FOUND"}},
            ["not", "a", "dict"],
            SaveAPIError("HTTP_502", "bad gateway", status_code=502),
            requests.Timeout("slow"),
            {"success": True, "id": "ok"},
        ]

        assert list(user.fetch_post_details()) == [{"success": True, "id": "ok"}]
        assert mock_fetch.call_count == 5  # noqa: PLR2004

    def test_http_rate_limit_is_raised(self, mock_fetch):
        """A 429 stops the loop so the caller can back off."""
        user = InstagramUserFactory(raw_api_data=_recent_posts("u1", "u2"))
        mock_fetch.side_effect = SaveAPIError("HTTP_429", "slow down", status_code=429)

        with pytest.raises(SaveAPIError) as exc_info:
            list(user.fetch_post_details())

        assert exc_info.value.is_rate_limited
        mock_fetch.assert_called_once()

    def test_body_rate_limit_is_raised(self, mock_fetch):
        """A RATE_LIMITED error body is raised even without a 429."""
        user = InstagramUserFactory(raw_api_data=_recent_posts("u1"))
        mock_fetch.return_value = {"success": False, "error": {"code": "RATE_LIMITED"}}

        with pytest.raises(SaveAPIError, match="RATE_LIMITED"):
            list(user.fetch_post_details())

    def test_missing_configuration_is_raised(self, mock_fetch):
        """Missing SaveAPI settings are not swallowed as a per-post failure."""
        user = InstagramUserFactory(raw_api_data=_recent_posts("u1"))
        mock_fetch.side_effect = ImproperlyConfigured("no key")

        with pytest.raises(ImproperlyConfigured):
            list(user.fetch_post_details())


def _saveapi_post(**overrides):
    """Return a SaveAPI post detail response shaped like a single photo."""
    response = {
        "success": True,
        "type": "image",
        "meta": {
            "text": "Just a pause.",
            "thumbnail": "https://cdn.example.com/thumb.jpg",
            "published_at": 1794276049,
        },
        "medias": [{"type": "image", "url": "https://cdn.example.com/full.jpg"}],
        "video_id": "4027001720088057574",
        "credits": {"spent": 1.5, "remaining": 100},
    }
    response.update(overrides)
    return response


class TestUserGetPostType(TestCase):
    """Tests for the User._get_post_type method."""

    def test_album_returns_carousel(self):
        """An album response maps to POST_VARIANT_CAROUSEL."""
        assert (
            User._get_post_type(_saveapi_post(type="album"))  # noqa: SLF001
            == Post.POST_VARIANT_CAROUSEL
        )

    def test_video_returns_video(self):
        """A video response maps to POST_VARIANT_VIDEO."""
        assert (
            User._get_post_type(_saveapi_post(type="video"))  # noqa: SLF001
            == Post.POST_VARIANT_VIDEO
        )

    def test_image_returns_normal(self):
        """An image response maps to POST_VARIANT_NORMAL."""
        assert (
            User._get_post_type(_saveapi_post(type="image"))  # noqa: SLF001
            == Post.POST_VARIANT_NORMAL
        )

    def test_unknown_type_raises_value_error(self):
        """An unknown, missing or non-string type raises ValueError."""
        for bad_response in (
            _saveapi_post(type="reel"),
            _saveapi_post(type=""),
            _saveapi_post(type=None),
            _saveapi_post(type=["album"]),
            {},
            None,
        ):
            with pytest.raises(ValueError, match="Unknown post type:"):
                User._get_post_type(bad_response)  # noqa: SLF001


class TestUserSavePostFromSaveapi(TestCase):
    """Tests for the User.save_post_from_saveapi method."""

    def test_creates_post_with_raw_data(self):
        """A new post gets its fields from the response, minus credits."""
        user = InstagramUserFactory()

        post = user.save_post_from_saveapi(_saveapi_post())

        post.refresh_from_db()
        assert post.id == "4027001720088057574"
        assert post.user == user
        assert post.variant == Post.POST_VARIANT_NORMAL
        assert post.caption == "Just a pause."
        assert post.thumbnail_url == "https://cdn.example.com/full.jpg"
        assert post.post_created_at == datetime.fromtimestamp(1794276049, tz=UTC)
        assert "credits" not in post.raw_data
        assert post.raw_data["video_id"] == "4027001720088057574"

    def test_album_is_carousel(self):
        """An album response is saved as a carousel post."""
        user = InstagramUserFactory()

        post = user.save_post_from_saveapi(_saveapi_post(type="album"))

        assert post.variant == Post.POST_VARIANT_CAROUSEL

    def test_video_is_video(self):
        """A video response is saved as a video post."""
        user = InstagramUserFactory()

        post = user.save_post_from_saveapi(_saveapi_post(type="video"))

        assert post.variant == Post.POST_VARIANT_VIDEO

    def test_unknown_type_raises_value_error(self):
        """An unknown post type raises ValueError and saves nothing."""
        user = InstagramUserFactory()

        with pytest.raises(ValueError, match="Unknown post type: 'reel'"):
            user.save_post_from_saveapi(_saveapi_post(type="reel"))

        assert not Post.objects.exists()

    def test_existing_post_is_left_alone(self):
        """A post that is already stored keeps its owner and fields."""
        existing = PostFactory(id="4027001720088057574", caption="old")
        user = InstagramUserFactory()

        post = user.save_post_from_saveapi(_saveapi_post())

        post.refresh_from_db()
        assert post.user == existing.user
        assert post.caption == "old"
        assert Post.objects.count() == 1

    def test_video_thumbnail_url_is_the_video(self):
        """A video post keeps its first media URL, even if meta.thumbnail differs."""
        user = InstagramUserFactory()
        response = _saveapi_post(
            type="video",
            medias=[{"type": "video", "url": "https://cdn.example.com/clip.mp4"}],
        )

        post = user.save_post_from_saveapi(response)

        assert post.thumbnail_url == "https://cdn.example.com/clip.mp4"

    def test_missing_media_url_defaults_to_empty_string(self):
        """Without a usable first media the thumbnail_url is empty."""
        user = InstagramUserFactory()

        for medias in ([], [{"type": "image"}], None, ["not-a-dict"]):
            Post.objects.all().delete()
            post = user.save_post_from_saveapi(_saveapi_post(medias=medias))

            assert post.thumbnail_url == ""

    def test_missing_video_id_returns_none(self):
        """A response without video_id saves nothing."""
        user = InstagramUserFactory()

        assert user.save_post_from_saveapi(_saveapi_post(video_id=None)) is None
        assert not Post.objects.exists()


class TestUserUpdatePostsFromApi(TestCase):
    """Tests for User.update_posts_from_api and update_posts_from_api_async."""

    @patch("instagram.models.user.User.fetch_post_details")
    def test_saves_each_fetched_post(self, mock_details):
        """Every valid post from fetch_post_details is saved and returned."""
        user = InstagramUserFactory()
        mock_details.return_value = iter(
            [
                _saveapi_post(video_id="101", type="image"),
                _saveapi_post(video_id="102", type="video"),
            ],
        )

        saved = user.update_posts_from_api()

        assert [post.id for post in saved] == ["101", "102"]
        assert Post.objects.filter(user=user).count() == 2  # noqa: PLR2004

    @patch("instagram.models.user.User.fetch_post_details")
    def test_skips_unknown_type_and_missing_video_id(self, mock_details):
        """Posts with an unknown type or no video_id are skipped without stopping."""
        user = InstagramUserFactory()
        mock_details.return_value = iter(
            [
                _saveapi_post(video_id="101", type="reel"),
                _saveapi_post(video_id=None, type="image"),
                _saveapi_post(video_id="103", type="album"),
            ],
        )

        saved = user.update_posts_from_api()

        assert [post.id for post in saved] == ["103"]
        assert saved[0].variant == Post.POST_VARIANT_CAROUSEL

    @patch("instagram.models.user.User.fetch_post_details")
    def test_rate_limit_propagates(self, mock_details):
        """A rate limit from fetch_post_details is not swallowed."""
        user = InstagramUserFactory()
        mock_details.side_effect = SaveAPIError(
            "RATE_LIMITED",
            "slow down",
            status_code=429,
            retryable=True,
        )

        with pytest.raises(SaveAPIError, match="RATE_LIMITED"):
            user.update_posts_from_api()

    @patch("instagram.tasks.update_user_posts_from_api.delay")
    def test_async_queues_task(self, mock_delay):
        """update_posts_from_api_async queues the Celery task."""
        user = InstagramUserFactory()

        user.update_posts_from_api_async()

        mock_delay.assert_called_once_with(user.uuid)


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
        assert user.raw_api_data["recent_posts"] == [{"id": "1", "shortcode": "abc"}]
        assert user.raw_api_data["id"] == "111"

    @patch("instagram.signals.user.update_profile_picture_from_url.delay")
    @patch("instagram.tasks.update_user_posts_from_api.delay")
    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_queues_post_update_on_commit(
        self,
        mock_fetch,
        mock_posts_delay,
        mock_pic_delay,
    ):
        """Committing a profile update queues update_user_posts_from_api."""
        user = InstagramUserFactory(username="testuser", instagram_id="111")
        mock_fetch.return_value = _saveapi_profile()

        with self.captureOnCommitCallbacks(execute=True):
            user.update_profile_from_api()

        mock_posts_delay.assert_called_once_with(user.uuid)

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
