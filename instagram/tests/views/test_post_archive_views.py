from datetime import timedelta
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.users.tests.factories import UserFactory
from core.utils.saveapi import SaveAPIError
from instagram.models import Post
from instagram.models import PostMedia
from instagram.models import User as InstagramUser
from instagram.tests.factories import InstagramUserFactory
from instagram.tests.factories import PostFactory
from instagram.throttles import PostArchiveRateThrottle
from instagram.utils import shortcode_to_media_id


def _saveapi_post_response(**overrides):
    """Build a valid SaveAPI /v1/download post payload."""
    meta = {
        "text": "Archived caption",
        "thumbnail": "https://cdn.example.com/thumb.jpg",
        "published_at": 1794276049,
        "username": "Alice.Example",
        "author": "Alice Example",
        "author_url": "https://www.instagram.com/alice.example/",
        "author_avatar": "https://cdn.example.com/avatar.jpg",
        "author_verified": True,
    }
    if "meta" in overrides and isinstance(overrides["meta"], dict):
        meta = {**meta, **overrides.pop("meta")}
    payload = {
        "success": True,
        "platform": "instagram",
        "type": "album",
        "video_id": "4027001720088057574",
        "meta": meta,
        "medias": [
            {"type": "image", "url": "https://cdn.example.com/1.jpg"},
            {"type": "video", "url": "https://cdn.example.com/2.mp4"},
        ],
        "credits": {"spent": 1, "remaining": 99},
    }
    payload.update(overrides)
    return payload


class PostArchiveViewTest(TestCase):
    """Tests for POST /instagram/posts/."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.url = reverse("instagram:post_list")
        self.django_user = UserFactory()
        self.client.force_authenticate(user=self.django_user)

    def test_unauthenticated_request_is_rejected(self):
        unauthenticated = APIClient()
        response = unauthenticated.post(
            self.url,
            {"url": "https://www.instagram.com/p/C_abc123/"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("instagram.models.post.fetch_post_detail")
    def test_invalid_url_returns_400_without_calling_saveapi(self, mock_fetch):
        for bad_url in (
            "https://www.instagram.com/stories/alice/123/",
            "https://evil.com/p/C_abc123/",
            "https://www.instagram.com/../p/C_abc123/",
        ):
            response = self.client.post(self.url, {"url": bad_url}, format="json")
            assert response.status_code == status.HTTP_400_BAD_REQUEST

        mock_fetch.assert_not_called()

    @patch("instagram.tasks.post.download_post_media_from_url.delay")
    @patch("instagram.tasks.post.download_post_thumbnail_from_url.delay")
    @patch("instagram.tasks.user.auto_update_user_profile.delay")
    @patch("instagram.models.post.fetch_post_detail")
    def test_archive_new_post_creates_stub_user_and_queues_profile_sync(
        self,
        mock_fetch,
        mock_sync_profile,
        mock_thumb_dl,
        mock_media_dl,
    ):
        mock_fetch.return_value = _saveapi_post_response()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url,
                {
                    "url": "https://www.instagram.com/p/C_abc123/?utm_source=ig",
                },
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["id"] == "4027001720088057574"
        assert response.data["variant"] == Post.POST_VARIANT_CAROUSEL
        assert len(response.data["media"]) == 2  # noqa: PLR2004

        stub_user = InstagramUser.objects.get(username="alice.example")
        assert stub_user.original_profile_picture_url == ""

        # Stub creation must not have a history_user so add-user quota stays intact.
        initial_history = stub_user.history.order_by("history_date").first()
        assert initial_history is not None
        assert initial_history.history_user is None

        mock_sync_profile.assert_called_once_with(
            str(stub_user.uuid),
            force=True,
            update_posts=False,
        )
        mock_thumb_dl.assert_not_called()
        mock_media_dl.assert_not_called()
        assert PostMedia.objects.filter(post_id="4027001720088057574").count() == 2  # noqa: PLR2004

    @patch("instagram.tasks.user.auto_update_user_profile.delay")
    @patch("instagram.models.post.fetch_post_detail")
    def test_stub_user_creation_does_not_exhaust_add_user_quota(
        self,
        mock_fetch,
        mock_sync_profile,
    ):
        for idx in range(4):
            mock_fetch.return_value = _saveapi_post_response(
                video_id=f"500000000000000000{idx}",
                meta={"username": f"author_{idx}", "author": f"Author {idx}"},
            )
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(
                    self.url,
                    {"url": f"https://www.instagram.com/p/Code{idx}A/"},
                    format="json",
                )
            assert resp.status_code == status.HTTP_201_CREATED

        with patch(
            "instagram.serializers.users.InstagramUser.update_profile_from_api",
        ):
            add_user_resp = self.client.post(
                reverse("instagram:user_list"),
                {"username": "manual_user"},
                format="json",
            )
        assert add_user_resp.status_code == status.HTTP_201_CREATED
        assert mock_sync_profile.call_count == 4  # noqa: PLR2004

    @patch("instagram.tasks.user.auto_update_user_profile.delay")
    @patch("instagram.models.post.fetch_post_detail")
    def test_archive_new_post_reuses_existing_user_case_insensitively(
        self,
        mock_fetch,
        mock_sync_profile,
    ):
        existing_user = InstagramUserFactory(username="Alice.Existing")
        mock_fetch.return_value = _saveapi_post_response(
            meta={"username": "alice.existing"},
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.url,
                {"url": "https://www.instagram.com/p/C_abc123/"},
                format="json",
            )

        assert response.status_code == status.HTTP_201_CREATED
        post = Post.objects.get(id="4027001720088057574")
        assert post.user == existing_user
        mock_sync_profile.assert_not_called()

    @patch("instagram.models.post.fetch_post_detail")
    def test_archive_existing_post_by_shortcode_skips_saveapi(self, mock_fetch):
        shortcode = "C_abc123"
        media_id = shortcode_to_media_id(shortcode)
        assert media_id is not None
        existing_post = PostFactory(id=media_id)

        response = self.client.post(
            self.url,
            {"url": f"https://www.instagram.com/p/{shortcode}/"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == existing_post.id
        mock_fetch.assert_not_called()

    @patch("instagram.models.post.fetch_post_detail")
    def test_archive_existing_post_via_share_url_without_author_meta_returns_200(
        self,
        mock_fetch,
    ):
        existing_post = PostFactory(id="4027001720088057574", caption="keep-me")
        mock_fetch.return_value = _saveapi_post_response(
            meta={"username": None},
        )

        response = self.client.post(
            self.url,
            {"url": "https://www.instagram.com/share/BA12345678/"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        existing_post.refresh_from_db()
        assert existing_post.caption == "keep-me"

    @patch("instagram.models.post.fetch_post_detail")
    def test_saveapi_error_mappings_do_not_leak_upstream_url(self, mock_fetch):
        cases = [
            (
                ImproperlyConfigured("SaveAPI URL missing"),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                None,
            ),
            (
                SaveAPIError(
                    "RATE_LIMITED",
                    "https://secret-saveapi.internal/v1/download",
                    status_code=429,
                    retryable=True,
                    retry_after=15,
                ),
                status.HTTP_429_TOO_MANY_REQUESTS,
                "15",
            ),
            (
                SaveAPIError("NOT_FOUND", "missing", status_code=404),
                status.HTTP_404_NOT_FOUND,
                None,
            ),
            (
                SaveAPIError("INVALID_URL", "bad url", status_code=400),
                status.HTTP_400_BAD_REQUEST,
                None,
            ),
            (
                SaveAPIError(
                    "HTTP_502",
                    "502 for url: https://secret-saveapi.internal/v1/download",
                    status_code=502,
                    retryable=True,
                ),
                status.HTTP_502_BAD_GATEWAY,
                None,
            ),
            (requests.Timeout("timed out"), status.HTTP_504_GATEWAY_TIMEOUT, None),
            (requests.ConnectionError("refused"), status.HTTP_502_BAD_GATEWAY, None),
        ]

        for exc, expected_status, retry_after in cases:
            mock_fetch.side_effect = exc
            response = self.client.post(
                self.url,
                {"url": "https://www.instagram.com/share/Token123/"},
                format="json",
            )
            assert response.status_code == expected_status
            assert "secret-saveapi.internal" not in str(response.data)
            if retry_after is not None:
                assert response.headers.get("Retry-After") == retry_after

    @patch("instagram.models.post.fetch_post_detail")
    def test_malformed_saveapi_payloads_return_502_and_save_nothing(self, mock_fetch):
        bad_payloads = [
            "not-a-dict",
            {"success": False, "error": "rate limited"},
            _saveapi_post_response(video_id=True),
            _saveapi_post_response(meta=["not", "a", "dict"]),
            _saveapi_post_response(meta={"username": "../admin"}),
            _saveapi_post_response(meta={"username": None}),
        ]

        for payload in bad_payloads:
            mock_fetch.return_value = payload
            response = self.client.post(
                self.url,
                {"url": "https://www.instagram.com/share/Token123/"},
                format="json",
            )
            assert response.status_code == status.HTTP_502_BAD_GATEWAY
            assert not Post.objects.exists()

    @patch("instagram.models.post.fetch_post_detail")
    def test_handles_extreme_published_at_and_nul_bytes(self, mock_fetch):
        mock_fetch.return_value = _saveapi_post_response(
            meta={
                "text": "hello\x00world",
                "published_at": 1e20,
            },
        )

        response = self.client.post(
            self.url,
            {"url": "https://www.instagram.com/p/C_abc123/"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["caption"] == "helloworld"

    @patch("instagram.models.post.fetch_post_detail")
    def test_daily_quota_of_100_posts_is_enforced_per_user(self, mock_fetch):
        author = InstagramUserFactory()
        posts = [PostFactory(user=author) for _ in range(100)]
        Post.history.filter(id__in=[p.id for p in posts]).update(
            history_user=self.django_user,
            history_date=timezone.now() - timedelta(hours=1),
        )

        response = self.client.post(
            self.url,
            {"url": "https://www.instagram.com/p/Quota101/"},
            format="json",
        )
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        mock_fetch.assert_not_called()

        # Another authenticated user still has their own quota.
        other_user = UserFactory()
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        mock_fetch.return_value = _saveapi_post_response(
            video_id="9999999999999999999",
            meta={"username": author.username},
        )
        other_resp = other_client.post(
            self.url,
            {"url": "https://www.instagram.com/p/QuotaOther/"},
            format="json",
        )
        assert other_resp.status_code == status.HTTP_201_CREATED

    def test_request_rate_throttle_rejects_excessive_post_requests_but_not_get(self):
        with (
            patch.object(
                PostArchiveRateThrottle,
                "get_rate",
                return_value="2/day",
            ),
            patch("instagram.models.post.fetch_post_detail") as mock_fetch,
        ):
            mock_fetch.side_effect = SaveAPIError(
                "NOT_FOUND",
                "missing",
                status_code=404,
            )
            for _ in range(2):
                resp = self.client.post(
                    self.url,
                    {"url": "https://www.instagram.com/share/Fake1/"},
                    format="json",
                )
                assert resp.status_code == status.HTTP_404_NOT_FOUND

            throttled = self.client.post(
                self.url,
                {"url": "https://www.instagram.com/share/Fake2/"},
                format="json",
            )
            assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS

            get_resp = self.client.get(self.url)
            assert get_resp.status_code == status.HTTP_200_OK

    @patch("instagram.models.user.User.update_posts_from_api_async")
    @patch("instagram.models.user.fetch_user_profile")
    def test_update_profile_from_api_skips_posts_when_requested(
        self,
        mock_profile,
        mock_update_posts,
    ):
        user = InstagramUserFactory(
            username="sync_only_user",
            instagram_id="123456789",
        )
        mock_profile.return_value = {
            "success": True,
            "id": "123456789",
            "username": "sync_only_user",
            "full_name": "Synced Name",
        }

        with self.captureOnCommitCallbacks(execute=True):
            user.update_profile_from_api(update_posts=False)

        mock_update_posts.assert_not_called()
