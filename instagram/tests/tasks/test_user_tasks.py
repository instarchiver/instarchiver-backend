from unittest.mock import Mock
from unittest.mock import patch

import requests
from celery.result import EagerResult
from django.core.files.base import ContentFile
from django.test import TestCase
from django.test import override_settings

from instagram.models import User
from instagram.tasks import auto_update_user_profile
from instagram.tasks import auto_update_user_story
from instagram.tasks import auto_update_users_profile
from instagram.tasks import auto_update_users_story
from instagram.tasks import update_profile_picture_from_url
from instagram.tasks import update_user_posts_from_api
from instagram.tasks import update_user_stories_from_api
from instagram.tests.factories import InstagramUserFactory


class TestUpdateProfilePictureFromUrl(TestCase):
    """Tests for the update_profile_picture_from_url Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.requests.get")
    def test_update_profile_picture_success(self, mock_get):
        """Test successful profile picture download and save."""
        user = InstagramUserFactory(
            username="testuser",
            original_profile_picture_url="https://example.com/profile.jpg",
        )

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.content = b"new_image_content"
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Execute the task
        result = update_profile_picture_from_url.delay(str(user.uuid))

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert "Profile picture updated" in result.result["message"]

        # Verify requests.get was called with correct URL
        mock_get.assert_called_once_with(
            user.original_profile_picture_url,
            timeout=30,
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.requests.get")
    def test_update_profile_picture_hash_unchanged(self, mock_get):
        """Test that profile picture is not updated if hash is unchanged."""
        user = InstagramUserFactory(
            username="testuser",
            original_profile_picture_url="https://example.com/profile.jpg",
        )

        # Set up existing profile picture
        image_content = b"existing_image_content"
        user.profile_picture.save(
            "testuser_profile.jpg",
            ContentFile(image_content),
            save=True,
        )

        # Mock the HTTP response with same content
        mock_response = Mock()
        mock_response.content = image_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Execute the task
        result = update_profile_picture_from_url.delay(str(user.uuid))

        # Verify the task detected no changes
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert "No changes detected" in result.result["message"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_update_profile_picture_user_not_found(self):
        """Test handling of non-existent user."""
        # Execute the task with non-existent user ID
        result = update_profile_picture_from_url.delay(
            "00000000-0000-0000-0000-000000000000",
        )

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_update_profile_picture_no_url(self):
        """Test handling when user has no original profile picture URL."""
        user = InstagramUserFactory(
            username="testuser",
            original_profile_picture_url="",
        )

        # Execute the task
        result = update_profile_picture_from_url.delay(str(user.uuid))

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "No original profile picture URL" in result.result["error"]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.requests.get")
    def test_update_profile_picture_network_error(self, mock_get):
        """Test retry logic on network errors."""
        user = InstagramUserFactory(
            username="testuser",
            original_profile_picture_url="https://example.com/profile.jpg",
        )

        # Mock a network error
        mock_get.side_effect = requests.RequestException("Network timeout")

        # Execute the task
        result = update_profile_picture_from_url.delay(str(user.uuid))

        # Verify the task returns an error after retries
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "error" in result.result

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.requests.get")
    def test_update_profile_picture_saves_file(self, mock_get):
        """Test that profile picture file is saved correctly."""
        user = InstagramUserFactory(
            username="testuser",
            original_profile_picture_url="https://example.com/profile.jpg",
        )

        # Mock the HTTP response
        new_content = b"new_profile_picture_content"
        mock_response = Mock()
        mock_response.content = new_content
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        # Execute the task
        result = update_profile_picture_from_url.delay(str(user.uuid))

        # Verify the task executed successfully
        assert result.result["success"] is True

        # Verify the user's profile picture was updated
        user.refresh_from_db()
        assert user.profile_picture.name != ""


class TestUpdateUserStoriesFromApi(TestCase):
    """Tests for the update_user_stories_from_api Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User._update_stories_from_api")
    def test_update_user_stories_success(self, mock_update_stories):
        """Test successful story update from API."""
        user = InstagramUserFactory(username="testuser")

        # Mock the model method to return some stories
        mock_update_stories.return_value = [{"id": "123"}, {"id": "456"}]

        # Execute the task
        result = update_user_stories_from_api.delay(str(user.uuid))

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["stories_count"] == 2  # noqa: PLR2004
        assert result.result["username"] == user.username

        # Verify the model method was called
        mock_update_stories.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_update_user_stories_user_not_found(self):
        """Test handling of non-existent user."""
        # Execute the task with non-existent user ID
        result = update_user_stories_from_api.delay(
            "00000000-0000-0000-0000-000000000000",
        )

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User._update_stories_from_api")
    def test_update_user_stories_api_error_retry(self, mock_update_stories):
        """Test retry logic on API errors."""
        user = InstagramUserFactory(username="testuser")

        # Mock an API error
        mock_update_stories.side_effect = Exception("API error: rate limit exceeded")

        # Execute the task
        result = update_user_stories_from_api.delay(str(user.uuid))

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "error" in result.result

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User._update_stories_from_api")
    def test_update_user_stories_empty_response(self, mock_update_stories):
        """Test handling of empty story list from API."""
        user = InstagramUserFactory(username="testuser")

        # Mock empty response
        mock_update_stories.return_value = []

        # Execute the task
        result = update_user_stories_from_api.delay(str(user.uuid))

        # Verify the task executed successfully with 0 stories
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["stories_count"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User._update_stories_from_api")
    def test_update_user_stories_non_retryable_error(self, mock_update_stories):
        """Test handling of non-retryable errors."""
        user = InstagramUserFactory(username="testuser")

        # Mock a non-retryable error
        mock_update_stories.side_effect = Exception("Invalid data format")

        # Execute the task
        result = update_user_stories_from_api.delay(str(user.uuid))

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Invalid data format" in result.result["error"]


class TestUpdateUserPostsFromApi(TestCase):
    """Tests for the update_user_posts_from_api Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User._update_post_data_from_api")
    def test_update_user_posts_success(self, mock_update_posts):
        """Test successful post update from API with pagination."""
        user = InstagramUserFactory(username="testuser")

        # Mock the model method to return pagination summary
        mock_update_posts.return_value = {
            "total_posts": 150,
            "pages_fetched": 3,
            "last_max_id": "3030736341848451381_4060475001",
        }

        # Execute the task
        result = update_user_posts_from_api.delay(str(user.uuid))

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["username"] == user.username
        assert result.result["total_posts"] == 150  # noqa: PLR2004
        assert result.result["pages_fetched"] == 3  # noqa: PLR2004

        # Verify the model method was called
        mock_update_posts.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_update_user_posts_user_not_found(self):
        """Test handling of non-existent user."""
        # Execute the task with non-existent user ID
        result = update_user_posts_from_api.delay(
            "00000000-0000-0000-0000-000000000000",
        )

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User._update_post_data_from_api")
    def test_update_user_posts_api_error_retry(self, mock_update_posts):
        """Test retry logic on API errors."""
        user = InstagramUserFactory(username="testuser")

        # Mock an API error
        mock_update_posts.side_effect = Exception("Network timeout")

        # Execute the task
        result = update_user_posts_from_api.delay(str(user.uuid))

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "error" in result.result

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User._update_post_data_from_api")
    def test_update_user_posts_rate_limit(self, mock_update_posts):
        """Test handling of API rate limiting."""
        user = InstagramUserFactory(username="testuser")

        # Mock a rate limit error
        mock_update_posts.side_effect = Exception("API error: rate limit exceeded")

        # Execute the task
        result = update_user_posts_from_api.delay(str(user.uuid))

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "rate limit" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User._update_post_data_from_api")
    def test_update_user_posts_non_retryable_error(self, mock_update_posts):
        """Test handling of non-retryable errors."""
        user = InstagramUserFactory(username="testuser")

        # Mock a non-retryable error
        mock_update_posts.side_effect = Exception("Invalid configuration")

        # Execute the task
        result = update_user_posts_from_api.delay(str(user.uuid))

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "Invalid configuration" in result.result["error"]


class TestAutoUpdateUsersProfile(TestCase):
    """Tests for the auto_update_users_profile Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.auto_update_user_profile.delay")
    def test_auto_update_users_profile_success(self, mock_task_delay):
        """Test successful queuing of profile update tasks."""
        # Create users with auto-update enabled
        InstagramUserFactory(username="user1", allow_auto_update_profile=True)
        InstagramUserFactory(username="user2", allow_auto_update_profile=True)
        InstagramUserFactory(username="user3", allow_auto_update_profile=True)

        # Create a user with auto-update disabled (should be skipped)
        InstagramUserFactory(username="user4", allow_auto_update_profile=False)

        # Mock the task delay to return a mock result
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Execute the task
        result = auto_update_users_profile.delay()

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 3  # noqa: PLR2004
        assert result.result["queued"] == 3  # noqa: PLR2004
        assert result.result["errors"] == 0

        # Verify auto_update_user_profile was called for each enabled user
        assert mock_task_delay.call_count == 3  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_update_users_profile_no_users(self):
        """Test when no users have auto-update enabled."""
        # Create only users with auto-update disabled
        InstagramUserFactory(username="user1", allow_auto_update_profile=False)
        InstagramUserFactory(username="user2", allow_auto_update_profile=False)

        # Execute the task
        result = auto_update_users_profile.delay()

        # Verify the task returns success with no users processed
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["updated"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.auto_update_user_profile.delay")
    def test_auto_update_users_profile_error_handling(self, mock_task_delay):
        """Test error handling when queuing tasks fails."""
        # Create users with auto-update enabled
        InstagramUserFactory(username="user1", allow_auto_update_profile=True)
        InstagramUserFactory(username="user2", allow_auto_update_profile=True)

        # Mock the task delay to raise an exception for the first user
        mock_task_delay.side_effect = [
            Exception("Task queue error"),
            Mock(id="task-id-123"),
        ]

        # Execute the task
        result = auto_update_users_profile.delay()

        # Verify the task completed with errors
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 2  # noqa: PLR2004
        assert result.result["queued"] == 1
        assert result.result["errors"] == 1
        assert result.result["error_details"] is not None

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_update_users_profile_empty_database(self):
        """Test when there are no users in the database."""
        # Ensure no users exist with auto-update enabled

        User.objects.filter(allow_auto_update_profile=True).delete()

        # Execute the task
        result = auto_update_users_profile.delay()

        # Verify the task returns success with no users
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["updated"] == 0


class TestAutoUpdateUserProfile(TestCase):
    """Tests for the auto_update_user_profile Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User.update_profile_from_api")
    def test_auto_update_user_profile_success(self, mock_update_profile):
        """Test successful profile update for a single user."""
        user = InstagramUserFactory(
            username="testuser",
            allow_auto_update_profile=True,
        )

        # Mock the model method
        mock_update_profile.return_value = None

        # Execute the task
        result = auto_update_user_profile.delay(str(user.uuid))

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["username"] == user.username

        # Verify the model method was called
        mock_update_profile.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_update_user_profile_disabled(self):
        """Test that update is skipped when auto-update is disabled."""
        user = InstagramUserFactory(
            username="testuser",
            allow_auto_update_profile=False,
        )

        # Execute the task
        result = auto_update_user_profile.delay(str(user.uuid))

        # Verify the task returns an error indicating auto-update is disabled
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not enabled" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_update_user_profile_user_not_found(self):
        """Test handling of non-existent user."""
        # Execute the task with non-existent user ID
        result = auto_update_user_profile.delay(
            "00000000-0000-0000-0000-000000000000",
        )

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User.update_profile_from_api")
    def test_auto_update_user_profile_api_error(self, mock_update_profile):
        """Test retry logic on API errors."""
        user = InstagramUserFactory(
            username="testuser",
            allow_auto_update_profile=True,
        )

        # Mock an API error
        mock_update_profile.side_effect = Exception("Network timeout")

        # Execute the task
        result = auto_update_user_profile.delay(str(user.uuid))

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "error" in result.result


class TestAutoUpdateUsersStory(TestCase):
    """Tests for the auto_update_users_story Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.auto_update_user_story.delay")
    def test_auto_update_users_story_success(self, mock_task_delay):
        """Test successful queuing of story update tasks."""
        # Create users with auto-update stories enabled
        InstagramUserFactory(username="user1", allow_auto_update_stories=True)
        InstagramUserFactory(username="user2", allow_auto_update_stories=True)
        InstagramUserFactory(username="user3", allow_auto_update_stories=True)

        # Create a user with auto-update disabled (should be skipped)
        InstagramUserFactory(username="user4", allow_auto_update_stories=False)

        # Mock the task delay to return a mock result
        mock_result = Mock()
        mock_result.id = "task-id-123"
        mock_task_delay.return_value = mock_result

        # Execute the task
        result = auto_update_users_story.delay()

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 3  # noqa: PLR2004
        assert result.result["queued"] == 3  # noqa: PLR2004
        assert result.result["errors"] == 0

        # Verify auto_update_user_story was called for each enabled user
        assert mock_task_delay.call_count == 3  # noqa: PLR2004

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_update_users_story_no_users(self):
        """Test when no users have auto-update stories enabled."""
        # Create only users with auto-update disabled
        InstagramUserFactory(username="user1", allow_auto_update_stories=False)
        InstagramUserFactory(username="user2", allow_auto_update_stories=False)

        # Execute the task
        result = auto_update_users_story.delay()

        # Verify the task returns success with no users processed
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.auto_update_user_story.delay")
    def test_auto_update_users_story_error_handling(self, mock_task_delay):
        """Test error handling when queuing tasks fails."""
        # Create users with auto-update enabled
        InstagramUserFactory(username="user1", allow_auto_update_stories=True)
        InstagramUserFactory(username="user2", allow_auto_update_stories=True)

        # Mock the task delay to raise an exception for the first user
        mock_task_delay.side_effect = [
            Exception("Task queue error"),
            Mock(id="task-id-123"),
        ]

        # Execute the task
        result = auto_update_users_story.delay()

        # Verify the task completed with errors
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["total"] == 2  # noqa: PLR2004
        assert result.result["queued"] == 1
        assert result.result["errors"] == 1
        assert result.result["error_details"] is not None

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_update_users_story_empty_database(self):
        """Test when there are no users in the database."""
        # Ensure no users exist with auto-update enabled
        User.objects.filter(allow_auto_update_stories=True).delete()

        # Execute the task
        result = auto_update_users_story.delay()

        # Verify the task returns success with no users
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["queued"] == 0


class TestAutoUpdateUserStory(TestCase):
    """Tests for the auto_update_user_story Celery task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User.update_stories_from_api")
    def test_auto_update_user_story_success(self, mock_update_stories):
        """Test successful story update for a single user."""
        user = InstagramUserFactory(
            username="testuser",
            allow_auto_update_stories=True,
        )

        # Mock the model method to return some stories
        mock_update_stories.return_value = [{"id": "123"}, {"id": "456"}]

        # Execute the task
        result = auto_update_user_story.delay(str(user.uuid))

        # Verify the task executed successfully
        assert isinstance(result, EagerResult)
        assert result.result["success"] is True
        assert result.result["username"] == user.username
        assert result.result["stories_count"] == 2  # noqa: PLR2004

        # Verify the model method was called
        mock_update_stories.assert_called_once()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_update_user_story_disabled(self):
        """Test that update is skipped when auto-update is disabled."""
        user = InstagramUserFactory(
            username="testuser",
            allow_auto_update_stories=False,
        )

        # Execute the task
        result = auto_update_user_story.delay(str(user.uuid))

        # Verify the task returns an error indicating auto-update is disabled
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not enabled" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_auto_update_user_story_user_not_found(self):
        """Test handling of non-existent user."""
        # Execute the task with non-existent user ID
        result = auto_update_user_story.delay(
            "00000000-0000-0000-0000-000000000000",
        )

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "not found" in result.result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.models.user.User.update_stories_from_api")
    def test_auto_update_user_story_api_error(self, mock_update_stories):
        """Test retry logic on API errors."""
        user = InstagramUserFactory(
            username="testuser",
            allow_auto_update_stories=True,
        )

        # Mock an API error
        mock_update_stories.side_effect = Exception("API error: rate limit exceeded")

        # Execute the task
        result = auto_update_user_story.delay(str(user.uuid))

        # Verify the task returns an error
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert "error" in result.result

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.auto_update_user_story.apply_async")
    @patch("instagram.models.user.User.update_stories_from_api")
    def test_auto_update_user_story_429_retries_with_delay(
        self,
        mock_update_stories,
        mock_apply_async,
    ):
        """Test that HTTP 429 triggers re-queue with delay and no retry limit."""
        user = InstagramUserFactory(
            username="testuser",
            allow_auto_update_stories=True,
        )

        # Create a mock 429 response
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_update_stories.side_effect = requests.exceptions.HTTPError(
            response=mock_response,
        )

        # Execute the task directly (bypass apply_async to avoid patching conflict)
        result = auto_update_user_story.apply(args=[str(user.uuid)])

        # Verify the task returned a failure result with retry info
        assert isinstance(result, EagerResult)
        assert result.result["success"] is False
        assert result.result["error"] == "Rate limited (429)"
        assert result.result["retry_in"] == 300  # noqa: PLR2004

        # Verify the task was re-queued with a countdown (no retry limit)
        mock_apply_async.assert_called_once()
        _, call_kwargs = mock_apply_async.call_args
        assert call_kwargs["countdown"] == 300  # noqa: PLR2004
        assert call_kwargs["args"] == [str(user.uuid)]

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("instagram.tasks.user.auto_update_user_story.apply_async")
    @patch("instagram.models.user.User.update_stories_from_api")
    def test_auto_update_user_story_429_uses_retry_after_header(
        self,
        mock_update_stories,
        mock_apply_async,
    ):
        """Test that HTTP 429 uses Retry-After header value as delay."""
        user = InstagramUserFactory(
            username="testuser",
            allow_auto_update_stories=True,
        )

        # Create a mock 429 response with Retry-After header
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "600"}
        mock_update_stories.side_effect = requests.exceptions.HTTPError(
            response=mock_response,
        )

        # Execute the task directly (bypass apply_async to avoid patching conflict)
        result = auto_update_user_story.apply(args=[str(user.uuid)])

        # Verify the task used the Retry-After header value
        assert isinstance(result, EagerResult)
        assert result.result["retry_in"] == 600  # noqa: PLR2004

        _, call_kwargs = mock_apply_async.call_args
        assert call_kwargs["countdown"] == 600  # noqa: PLR2004
