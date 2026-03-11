from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.users.tests.factories import UserFactory


class GetMeViewTestCase(TestCase):
    """Test suite for the GetMeView endpoint."""

    def setUp(self):
        """Set up test client and user for each test."""
        self.client = APIClient()
        self.user = UserFactory(
            email="testuser@example.com",
            username="testuser",
            name="Test User",
            photo_url="https://example.com/photo.jpg",
        )
        self.url = reverse("authentication:get-me")

    def test_get_me_authenticated_user(self):
        """Test that authenticated user can retrieve their information."""
        # Authenticate the user
        self.client.force_authenticate(user=self.user)

        # Make request to get-me endpoint
        response = self.client.get(self.url)

        # Assert response status
        assert response.status_code == status.HTTP_200_OK

        # Assert response data contains user information
        assert response.data["id"] == self.user.id
        assert response.data["email"] == self.user.email
        assert response.data["username"] == self.user.username
        assert response.data["name"] == self.user.name
        assert response.data["photo_url"] == self.user.photo_url

    def test_get_me_unauthenticated_user(self):
        """Test that unauthenticated user receives 403 error."""
        # Make request without authentication
        response = self.client.get(self.url)

        # Assert response status (DRF returns 403 due to global
        # IsAuthenticated permission)
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Assert error message from DRF
        assert "detail" in response.data

    def test_get_me_returns_correct_fields(self):
        """Test that the response contains only the expected fields."""
        # Authenticate the user
        self.client.force_authenticate(user=self.user)

        # Make request to get-me endpoint
        response = self.client.get(self.url)

        # Assert response status
        assert response.status_code == status.HTTP_200_OK

        # Assert response contains exactly the expected fields
        expected_fields = {"id", "username", "email", "name", "photo_url"}
        assert set(response.data.keys()) == expected_fields

    def test_get_me_with_invalid_token(self):
        """Test that request with invalid token receives 403 error."""
        # Set an invalid token
        self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid_token")

        # Make request to get-me endpoint
        response = self.client.get(self.url)

        # Assert response status (DRF returns 403 for invalid authentication)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_get_me_user_without_photo_url(self):
        """Test that user without photo_url can still retrieve their information."""
        # Create user without photo_url
        user = UserFactory(
            email="nophoto@example.com",
            username="nophoto",
            name="No Photo User",
            photo_url="",
        )

        # Authenticate the user
        self.client.force_authenticate(user=user)

        # Make request to get-me endpoint
        response = self.client.get(self.url)

        # Assert response status
        assert response.status_code == status.HTTP_200_OK

        # Assert photo_url is empty string
        assert response.data["photo_url"] == ""

    def test_get_me_only_accepts_get_method(self):
        """Test that the endpoint only accepts GET requests."""
        # Authenticate the user
        self.client.force_authenticate(user=self.user)

        # Test POST method
        response = self.client.post(self.url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Test PUT method
        response = self.client.put(self.url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Test PATCH method
        response = self.client.patch(self.url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Test DELETE method
        response = self.client.delete(self.url)
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


class JWTRefreshTokenLifetimeTestCase(TestCase):
    """Test suite for JWT refresh token lifetime configuration."""

    def test_refresh_token_lifetime_is_30_days(self):
        """Test that SIMPLE_JWT setting has REFRESH_TOKEN_LIFETIME of 30 days."""
        simple_jwt = getattr(settings, "SIMPLE_JWT", {})
        assert simple_jwt.get("REFRESH_TOKEN_LIFETIME") == timedelta(days=30)

    def test_generated_refresh_token_expires_in_30_days(self):
        """Test that a generated refresh token has a 30-day lifetime."""
        user = UserFactory()
        refresh = RefreshToken.for_user(user)

        token_lifetime = refresh.lifetime
        assert token_lifetime == timedelta(days=30)


class RefreshTokenViewTestCase(TestCase):
    """Test suite for the RefreshTokenView endpoint."""

    def setUp(self):
        """Set up test client and user for each test."""
        self.client = APIClient()
        self.user = UserFactory(
            email="refreshuser@example.com",
            username="refreshuser",
            name="Refresh User",
        )
        self.url = reverse("authentication:refresh-token")

    def test_refresh_token_returns_new_tokens(self):
        """Test that a valid refresh token returns new access and refresh tokens."""
        refresh = RefreshToken.for_user(self.user)

        response = self.client.post(
            self.url,
            {"refresh": str(refresh)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data

    def test_refresh_token_with_invalid_token_returns_400(self):
        """Test that an invalid refresh token returns a 400 error."""
        response = self.client.post(
            self.url,
            {"refresh": "invalid.token.value"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data

    def test_refresh_token_missing_token_returns_400(self):
        """Test that a missing refresh token returns a 400 error."""
        response = self.client.post(self.url, {}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
