from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.users.tests.factories import UserFactory
from instagram.models import User as InstagramUser
from instagram.tests.factories import InstagramUserFactory


class InstagramUserCreateViewTest(TestCase):
    """Tests for the POST (create) endpoint on InstagramUserListCreateView."""

    def setUp(self):
        """Set up authenticated client."""
        self.client = APIClient()
        self.url = reverse("instagram:user_list")
        self.django_user = UserFactory()
        self.client.force_authenticate(user=self.django_user)

    @patch("instagram.serializers.users.InstagramUser.update_profile_from_api")
    def test_create_user_success(self, mock_update):
        """Test successful Instagram user creation via POST."""
        mock_update.return_value = None
        response = self.client.post(
            self.url, {"username": "brandnewuser"}, format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert InstagramUser.objects.filter(username="brandnewuser").exists()

    @patch("instagram.serializers.users.InstagramUser.update_profile_from_api")
    def test_create_user_unauthenticated_rejected(self, mock_update):
        """Test that unauthenticated POST is rejected."""
        mock_update.return_value = None
        unauthenticated_client = APIClient()
        response = unauthenticated_client.post(
            self.url,
            {"username": "testuser"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @patch("instagram.serializers.users.InstagramUser.update_profile_from_api")
    def test_create_user_duplicate_username_returns_400(self, mock_update):
        """Test that creating a user with existing username returns 400."""
        mock_update.return_value = None
        InstagramUserFactory(username="existinguser")
        response = self.client.post(
            self.url,
            {"username": "existinguser"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("instagram.serializers.users.InstagramUser.update_profile_from_api")
    def test_create_user_rate_limit_enforced(self, mock_update):
        """Test that the rate limit of 3 creations per day is enforced."""
        mock_update.return_value = None
        max_per_day = 3

        # Create 3 users successfully
        for i in range(max_per_day):
            resp = self.client.post(
                self.url,
                {"username": f"ratelimituser{i}"},
                format="json",
            )
            assert resp.status_code == status.HTTP_201_CREATED

        # 4th creation should be rejected
        resp = self.client.post(
            self.url,
            {"username": "ratelimituser_extra"},
            format="json",
        )
        assert resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    @patch("instagram.serializers.users.InstagramUser.update_profile_from_api")
    def test_create_user_rate_limit_counts_only_current_user(self, mock_update):
        """Test that rate limiting is per-user and doesn't affect other users."""
        mock_update.return_value = None

        # Create 3 users with this user
        for i in range(3):
            self.client.post(
                self.url,
                {"username": f"user{i}"},
                format="json",
            )

        # A different authenticated user should still be able to create
        other_user = UserFactory()
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        resp = other_client.post(
            self.url,
            {"username": "other_users_instagram"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED

    @patch("instagram.serializers.users.InstagramUser.update_profile_from_api")
    def test_create_user_missing_username_returns_400(self, mock_update):
        """Test that missing username field returns 400."""
        mock_update.return_value = None
        response = self.client.post(self.url, {}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class InstagramUserAddStoryCreditViewTest(TestCase):
    """Tests for the InstagramUserAddStoryCreditAPIView endpoint."""

    def setUp(self):
        """Set up authenticated client and Instagram user."""
        self.client = APIClient()
        self.django_user = UserFactory()
        self.client.force_authenticate(user=self.django_user)
        self.instagram_user = InstagramUserFactory()
        self.url = reverse(
            "instagram:user_add_story_credit",
            kwargs={"uuid": self.instagram_user.uuid},
        )

    def test_unauthenticated_rejected(self):
        """Test that unauthenticated requests are rejected."""
        unauthenticated_client = APIClient()
        response = unauthenticated_client.post(
            self.url,
            {"story_credit": 5},
            format="json",
        )
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    @patch("instagram.views.users.stripe_create_instagram_user_story_credits_payment")
    def test_add_story_credit_success(self, mock_stripe):
        """Test successful story credit addition."""
        mock_stripe.return_value = {"id": "pi_test_123"}
        response = self.client.post(self.url, {"story_credit": 5}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert "detail" in response.data

    def test_negative_story_credit_returns_400(self):
        """Test that negative story_credit value returns 400."""
        response = self.client.post(self.url, {"story_credit": -1}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_story_credit_returns_400(self):
        """Test that missing story_credit field returns 400."""
        response = self.client.post(self.url, {}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
