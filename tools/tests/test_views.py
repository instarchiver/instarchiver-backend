from http import HTTPStatus
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.users.tests.factories import UserFactory
from tools.instagram import InstagramProfileError


class InstagramProfileDetailAPIViewTest(TestCase):
    """Tests for GET /tools/instagram/profile/?username=..."""

    def setUp(self):
        self.client = APIClient()
        self.django_user = UserFactory()
        self.url = reverse("tools:instagram_profile_detail")

    def test_unauthenticated_rejected(self):
        response = self.client.get(self.url, {"username": "someone"})
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_missing_or_invalid_username_returns_400(self):
        self.client.force_authenticate(user=self.django_user)
        for params in ({}, {"username": "@someone"}, {"username": "a/b"}):
            response = self.client.get(self.url, params)
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.data["code"] == "INVALID_USERNAME"

    @patch("tools.views.fetch_instagram_profile", return_value=None)
    def test_missing_profile_returns_404(self, mock_fetch):
        self.client.force_authenticate(user=self.django_user)

        response = self.client.get(self.url, {"username": "nobody"})

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data["code"] == "NOT_FOUND"
        mock_fetch.assert_called_once_with("nobody")

    @patch("tools.views.fetch_instagram_profile")
    def test_returns_profile_detail_without_rate_limit(self, mock_fetch):
        self.client.force_authenticate(user=self.django_user)
        payload = {
            "id": "32917698626",
            "graph_api_id": "17841432958784712",
            "username": "udon05310531",
            "full_name": "Test Name",
            "biography": "Bio",
            "pronouns": [],
            "bio_links": [],
            "profile_photo_url": "https://cdn.example/pic.jpg",
            "follower_count": 13563,
            "following_count": 6,
            "post_count": 70,
            "is_private": False,
            "is_verified": False,
            "restriction": None,
            "is_memorialized": False,
            "is_unpublished": False,
            "is_coppa_enforced": False,
            "has_reels": True,
            "latest_story_timestamp": None,
            "show_threads_badge": False,
            "account_badges": [],
            "linked_facebook": None,
            "highlights": [],
            "posts": [],
        }
        mock_fetch.return_value = payload

        for _ in range(15):
            response = self.client.get(self.url, {"username": "udon05310531"})
            assert response.status_code == status.HTTP_200_OK
            assert response.data == payload

    @patch("tools.views.fetch_instagram_profile")
    def test_maps_upstream_errors(self, mock_fetch):
        self.client.force_authenticate(user=self.django_user)
        for code, http_status in (
            ("RATE_LIMITED", HTTPStatus.TOO_MANY_REQUESTS),
            ("LOGIN_WALL", HTTPStatus.BAD_GATEWAY),
            ("UPSTREAM_ERROR", HTTPStatus.BAD_GATEWAY),
        ):
            mock_fetch.side_effect = InstagramProfileError(
                code,
                f"Error {code}",
                status_code=http_status,
            )
            response = self.client.get(self.url, {"username": "someone"})
            assert response.status_code == http_status
            assert response.data == {"detail": f"Error {code}", "code": code}
