from unittest.mock import MagicMock
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponseRedirect
from django.test import RequestFactory
from django.test import TestCase

from instagram.admin.user import InstagramUserAdmin
from instagram.models import User as InstagramUser
from instagram.tests.factories import InstagramUserFactory

DjangoUser = get_user_model()


class TestInstagramUserAdminActions(TestCase):
    """Tests for InstagramUserAdmin custom action methods."""

    def setUp(self):
        """Set up a fake request using RequestFactory and a superuser."""
        self.factory = RequestFactory()
        self.admin = InstagramUserAdmin(InstagramUser, None)
        self.user = InstagramUserFactory(username="admintest")
        # Create a superuser so request.user has all permissions
        self.superuser = DjangoUser.objects.create_superuser(
            username="adminsuper",
            password="testpassword123",  # noqa: S106
            email="adminsuper@example.com",
        )

    def _get_request_with_messages(self):
        """Helper to create a request that supports Django messages and auth."""
        request = self.factory.get("/")
        request.user = self.superuser
        request.session = {}
        request._messages = FallbackStorage(request)  # noqa: SLF001
        return request

    @patch("instagram.admin.user.User.update_profile_from_api")
    def test_update_from_api_success(self, mock_update):
        """Test update_from_api action calls update_profile_from_api and redirects."""
        mock_update.return_value = None
        request = self._get_request_with_messages()
        response = self.admin.update_from_api(request, object_id=str(self.user.pk))
        assert isinstance(response, HttpResponseRedirect)
        mock_update.assert_called_once()
        messages = list(get_messages(request))
        assert len(messages) == 1
        assert "Successfully updated" in str(messages[0])

    @patch("instagram.admin.user.User.update_profile_from_api")
    def test_update_from_api_error(self, mock_update):
        """Test update_from_api action handles errors gracefully."""
        mock_update.side_effect = Exception("API down")
        request = self._get_request_with_messages()
        response = self.admin.update_from_api(request, object_id=str(self.user.pk))
        assert isinstance(response, HttpResponseRedirect)
        messages = list(get_messages(request))
        assert len(messages) == 1
        assert "Failed to update" in str(messages[0])

    @patch("instagram.admin.user.User.update_stories_from_api_async")
    def test_update_stories_from_api_success(self, mock_async):
        """Test update_stories_from_api action queues task and redirects."""
        mock_result = MagicMock()
        mock_result.id = "task-abc"
        mock_async.return_value = mock_result
        request = self._get_request_with_messages()
        response = self.admin.update_stories_from_api(
            request,
            object_id=str(self.user.pk),
        )
        assert isinstance(response, HttpResponseRedirect)
        mock_async.assert_called_once()
        messages = list(get_messages(request))
        assert len(messages) == 1
        assert "Successfully queued" in str(messages[0])

    @patch("instagram.admin.user.User.update_stories_from_api_async")
    def test_update_stories_from_api_error(self, mock_async):
        """Test update_stories_from_api action handles errors gracefully."""
        mock_async.side_effect = Exception("Queue full")
        request = self._get_request_with_messages()
        response = self.admin.update_stories_from_api(
            request,
            object_id=str(self.user.pk),
        )
        assert isinstance(response, HttpResponseRedirect)
        messages = list(get_messages(request))
        assert len(messages) == 1
        assert "Failed to queue" in str(messages[0])

    @patch("instagram.admin.user.User.update_posts_from_api_async")
    def test_update_posts_from_api_success(self, mock_async):
        """Test update_posts_from_api action queues task and redirects."""
        mock_result = MagicMock()
        mock_result.id = "task-xyz"
        mock_async.return_value = mock_result
        request = self._get_request_with_messages()
        response = self.admin.update_posts_from_api(
            request,
            object_id=str(self.user.pk),
        )
        assert isinstance(response, HttpResponseRedirect)
        mock_async.assert_called_once()
        messages = list(get_messages(request))
        assert len(messages) == 1
        assert "Successfully queued" in str(messages[0])

    @patch("instagram.admin.user.User.update_posts_from_api_async")
    def test_update_posts_from_api_error(self, mock_async):
        """Test update_posts_from_api action handles errors gracefully."""
        mock_async.side_effect = Exception("Celery down")
        request = self._get_request_with_messages()
        response = self.admin.update_posts_from_api(
            request,
            object_id=str(self.user.pk),
        )
        assert isinstance(response, HttpResponseRedirect)
        messages = list(get_messages(request))
        assert len(messages) == 1
        assert "Failed to queue" in str(messages[0])
