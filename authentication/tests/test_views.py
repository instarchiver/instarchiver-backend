from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.users.tests.factories import UserFactory

User = get_user_model()
MAX_NAME_LENGTH = 255
MAX_PHOTO_URL_LENGTH = 255
MAX_EMAIL_LENGTH = 254
OVER_USERNAME_EMAIL_LOCAL_LENGTH = 150


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


class LoginWithGoogleViewTestCase(TestCase):
    """Test suite for the LoginWithGoogleView endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.url = reverse("authentication:google-login")

    def test_login_creates_new_user_and_returns_jwt_tokens(self):
        user_info = {
            "uid": "firebase-uid-1",
            "email": "alice@example.com",
            "email_verified": True,
            "name": "Alice",
            "photo_url": "https://example.com/alice.jpg",
        }
        with patch(
            "authentication.views.firebase.get_user_info",
            return_value=user_info,
        ) as mock_get_user_info:
            response = self.client.post(
                self.url,
                {"token": "firebase-id-token"},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data
        mock_get_user_info.assert_called_once_with("firebase-id-token")

        user = User.objects.get(email="alice@example.com")
        assert user.username == "alice@example.com"
        assert user.name == "Alice"
        assert user.photo_url == "https://example.com/alice.jpg"
        assert user.is_active is True

    def test_repeat_login_with_unchanged_profile_skips_update(self):
        UserFactory(
            email="alice@example.com",
            username="alice@example.com",
            name="Alice",
            photo_url="https://example.com/alice.jpg",
            is_active=True,
        )
        user_info = {
            "uid": "firebase-uid-1",
            "email": "alice@example.com",
            "email_verified": True,
            "name": "Alice",
            "photo_url": "https://example.com/alice.jpg",
        }
        with (
            patch(
                "authentication.views.firebase.get_user_info",
                return_value=user_info,
            ),
            CaptureQueriesContext(connection) as queries,
        ):
            response = self.client.post(
                self.url,
                {"token": "firebase-id-token"},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        update_queries = [
            query["sql"]
            for query in queries
            if query["sql"].lstrip().upper().startswith("UPDATE")
        ]
        assert update_queries == []

    def test_repeat_login_updates_changed_fields_and_reactivates_user(self):
        user = UserFactory(
            email="alice@example.com",
            username="alice@example.com",
            name="Old Name",
            photo_url="https://example.com/old.jpg",
            is_active=False,
        )
        user_info = {
            "uid": "firebase-uid-1",
            "email": "alice@example.com",
            "email_verified": True,
            "name": "New Name",
            "photo_url": "https://example.com/new.jpg",
        }
        with patch(
            "authentication.views.firebase.get_user_info",
            return_value=user_info,
        ):
            response = self.client.post(
                self.url,
                {"token": "firebase-id-token"},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.name == "New Name"
        assert user.photo_url == "https://example.com/new.jpg"
        assert user.is_active is True

    def test_repeat_login_preserves_profile_when_claims_missing_or_oversized(self):
        user = UserFactory(
            email="alice@example.com",
            username="alice@example.com",
            name="Alice",
            photo_url="https://example.com/alice.jpg",
        )
        oversized_photo = f"https://example.com/{'x' * MAX_PHOTO_URL_LENGTH}"
        for user_info in [
            {
                "uid": "firebase-uid-1",
                "email": "alice@example.com",
                "email_verified": True,
                "name": None,
                "photo_url": oversized_photo,
            },
            {
                "uid": "firebase-uid-1",
                "email": "alice@example.com",
                "email_verified": True,
            },
        ]:
            with patch(
                "authentication.views.firebase.get_user_info",
                return_value=user_info,
            ):
                response = self.client.post(
                    self.url,
                    {"token": "firebase-id-token"},
                    format="json",
                )

            assert response.status_code == status.HTTP_200_OK
            user.refresh_from_db()
            assert user.name == "Alice"
            assert user.photo_url == "https://example.com/alice.jpg"

    def test_new_user_with_missing_or_null_optional_claims(self):
        user_info = {
            "uid": "firebase-uid-2",
            "email": "bob@example.com",
            "email_verified": True,
            "name": None,
        }
        with patch(
            "authentication.views.firebase.get_user_info",
            return_value=user_info,
        ):
            response = self.client.post(
                self.url,
                {"token": "firebase-id-token"},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        user = User.objects.get(email="bob@example.com")
        assert user.name == ""
        assert user.photo_url == ""

    def test_new_user_truncates_oversized_name_and_drops_oversized_photo_url(self):
        long_name = "N" * (MAX_NAME_LENGTH + 40)
        long_photo = f"https://example.com/{'p' * MAX_PHOTO_URL_LENGTH}"
        user_info = {
            "uid": "firebase-uid-3",
            "email": "carol@example.com",
            "email_verified": True,
            "name": long_name,
            "photo_url": long_photo,
        }
        with patch(
            "authentication.views.firebase.get_user_info",
            return_value=user_info,
        ):
            response = self.client.post(
                self.url,
                {"token": "firebase-id-token"},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        user = User.objects.get(email="carol@example.com")
        assert user.name == "N" * MAX_NAME_LENGTH
        assert len(user.name) == MAX_NAME_LENGTH
        assert user.photo_url == ""

    def test_unverified_email_returns_401_and_blocks_account_matching(self):
        victim = UserFactory(
            email="victim@example.com",
            username="victim",
            name="Victim",
            is_active=False,
        )
        for user_info in [
            {
                "uid": "attacker-uid",
                "email": "victim@example.com",
                "email_verified": False,
                "name": "Attacker",
            },
            {
                "uid": "attacker-uid",
                "email": "victim@example.com",
                "name": "Attacker",
            },
        ]:
            with patch(
                "authentication.views.firebase.get_user_info",
                return_value=user_info,
            ):
                response = self.client.post(
                    self.url,
                    {"token": "firebase-id-token"},
                    format="json",
                )

            assert response.status_code == status.HTTP_401_UNAUTHORIZED

        victim.refresh_from_db()
        assert victim.name == "Victim"
        assert victim.is_active is False

    def test_invalid_or_missing_email_returns_401_without_matching_blank_user(self):
        blank_user = UserFactory(
            username="telegram_123",
            email="",
            name="Telegram User",
        )
        oversized_email = f"{'a' * MAX_EMAIL_LENGTH}@example.com"
        for bad_email in [None, "", "   ", oversized_email]:
            user_info = {
                "uid": "firebase-uid-4",
                "email": bad_email,
                "email_verified": True,
                "name": "Other",
            }
            with patch(
                "authentication.views.firebase.get_user_info",
                return_value=user_info,
            ):
                response = self.client.post(
                    self.url,
                    {"token": "firebase-id-token"},
                    format="json",
                )

            assert response.status_code == status.HTTP_401_UNAUTHORIZED

        blank_user.refresh_from_db()
        assert blank_user.name == "Telegram User"
        assert User.objects.count() == 1

    def test_long_email_between_151_and_254_chars_for_new_and_existing_user(self):
        long_email = f"{'a' * OVER_USERNAME_EMAIL_LOCAL_LENGTH}@example.com"
        user_info = {
            "uid": "firebase-uid-5",
            "email": long_email,
            "email_verified": True,
            "name": "Updated Name",
            "photo_url": "",
        }
        with patch(
            "authentication.views.firebase.get_user_info",
            return_value=user_info,
        ):
            new_user_response = self.client.post(
                self.url,
                {"token": "firebase-id-token"},
                format="json",
            )

        assert new_user_response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not User.objects.filter(email=long_email).exists()

        existing = UserFactory(
            username="existinglonguser",
            email=long_email,
            name="Original Name",
        )
        with patch(
            "authentication.views.firebase.get_user_info",
            return_value=user_info,
        ):
            existing_user_response = self.client.post(
                self.url,
                {"token": "firebase-id-token"},
                format="json",
            )

        assert existing_user_response.status_code == status.HTTP_200_OK
        existing.refresh_from_db()
        assert existing.name == "Updated Name"

    def test_firebase_verification_error_returns_401(self):
        with patch(
            "authentication.views.firebase.get_user_info",
            side_effect=ValueError("bad token"),
        ):
            response = self.client.post(
                self.url,
                {"token": "firebase-id-token"},
                format="json",
            )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
