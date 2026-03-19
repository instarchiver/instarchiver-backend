import contextlib
import hashlib
import logging
from http import HTTPStatus

import requests
from celery import shared_task
from django.core.files.base import ContentFile

from instagram.models import User

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def update_profile_picture_from_url(self, user_id):
    """
    Update user's profile picture from Instagram URL if content has changed.
    Uses hash comparison to detect actual image content changes.
    """
    try:
        user = User.objects.get(uuid=user_id)
    except User.DoesNotExist:
        logger.exception("User with ID %s not found", user_id)
        return {"success": False, "error": "User not found"}

    if not user.original_profile_picture_url:
        logger.info("No original profile picture URL for user %s", user.username)
        return {"success": False, "error": "No original profile picture URL"}

    try:
        # Download image from Instagram URL
        response = requests.get(user.original_profile_picture_url, timeout=30)
        response.raise_for_status()

        # Calculate hash of downloaded image content
        new_image_content = response.content
        new_image_hash = hashlib.sha256(new_image_content).hexdigest()

        # Get hash of existing profile picture if it exists (S3-compatible)
        existing_image_hash = None
        if user.profile_picture:
            try:
                with user.profile_picture.open("rb") as f:
                    existing_content = f.read()
                    existing_image_hash = hashlib.sha256(existing_content).hexdigest()
            except OSError as e:
                logger.warning(
                    "Could not read existing profile picture for %s: %s",
                    user.username,
                    e,
                )

        # Compare hashes - only update if different
        if existing_image_hash == new_image_hash:
            logger.info("Profile picture unchanged for user %s", user.username)
            return {"success": True, "message": "No changes detected"}

        # Save new image
        # Extract filename from URL or use default
        filename = f"{user.username}_profile.jpg"

        # Save the new image
        user.profile_picture.save(
            filename,
            ContentFile(new_image_content),
            save=False,  # Don't save model yet to avoid triggering signal again
        )

        # Update using queryset to avoid triggering signals
        User.objects.filter(uuid=user.uuid).update(
            profile_picture=user.profile_picture.name,
        )

        logger.info("Profile picture updated for user %s", user.username)
        return {  # noqa: TRY300
            "success": True,
            "message": "Profile picture updated",
            "old_hash": existing_image_hash,
            "new_hash": new_image_hash,
        }

    except (requests.RequestException, OSError) as e:
        # Retryable errors: network issues, S3 timeouts, temporary file access issues
        logger.warning(
            "Retryable error updating profile picture for %s (attempt %s/%s): %s",
            user.username,
            self.request.retries + 1,
            self.max_retries + 1,
            e,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        logger.exception(
            "Max retries exceeded for profile picture update for %s",
            user.username,
        )
        return {"success": False, "error": f"Max retries exceeded: {e!s}"}

    except Exception as e:
        # Non-retryable errors: permanent failures
        logger.exception(
            "Permanent error updating profile picture for %s",
            user.username,
        )
        return {"success": False, "error": f"Permanent error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def update_user_stories_from_api(self, user_id):
    """
    Update user's stories from Instagram API in the background.
    Delegates business logic to the User model method.
    """
    try:
        user = User.objects.get(uuid=user_id)
    except User.DoesNotExist:
        logger.exception("User with ID %s not found", user_id)
        return {"success": False, "error": "User not found"}

    try:
        # Call the model method which handles all business logic
        updated_stories = user._update_stories_from_api()  # noqa: SLF001

        stories_count = len(updated_stories) if updated_stories else 0
        logger.info(
            "Successfully updated %d stories for user %s via Celery task",
            stories_count,
            user.username,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": f"Successfully updated {stories_count} stories",
            "stories_count": stories_count,
            "username": user.username,
        }

    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error updating stories for %s (attempt %s/%s): %s",
                user.username,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to update stories for user %s after %s attempts",
            user.username,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "username": user.username,
            "attempts": self.request.retries + 1,
        }


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def update_user_posts_from_api(self, user_id):
    """
    Update user's posts from Instagram API with full pagination support.
    Fetches all pages of posts using the max_id cursor.
    """
    try:
        user = User.objects.get(uuid=user_id)
    except User.DoesNotExist:
        logger.exception("User with ID %s not found", user_id)
        return {"success": False, "error": "User not found"}

    try:
        # Call the model method which handles pagination recursively
        result = user._update_post_data_from_api()  # noqa: SLF001

        logger.info(
            "Successfully updated %d posts across %d pages for user %s via Celery task",
            result["total_posts"],
            result["pages_fetched"],
            user.username,
        )

        return {
            "success": True,
            "message": (
                f"Successfully updated {result['total_posts']} posts "
                f"across {result['pages_fetched']} pages"
            ),
            "username": user.username,
            "total_posts": result["total_posts"],
            "pages_fetched": result["pages_fetched"],
        }

    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error updating posts for %s (attempt %s/%s): %s",
                user.username,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to update posts for user %s after %s attempts",
            user.username,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "username": user.username,
            "attempts": self.request.retries + 1,
        }


@shared_task
def auto_update_users_profile():
    """
    Update all users' profiles from Instagram API for users with auto-update enabled.
    Returns summary of operations performed.
    """
    try:
        # Get all users with auto-update profile enabled
        users = User.objects.filter(allow_auto_update_profile=True)
        total_users = users.count()

        if total_users == 0:
            logger.info("No users found with auto-update profile enabled")
            return {
                "success": True,
                "message": "No users to update",
                "updated": 0,
                "errors": 0,
            }

        logger.info("Starting profile update for %d users", total_users)

        updated_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for user in users:
            try:
                # Use Celery task to handle each user's profile update
                task_result = auto_update_user_profile.delay(str(user.uuid))
                task_ids.append(task_result.id)
                updated_count += 1
                logger.info(
                    "Successfully queued profile update for user: %s (task: %s)",
                    user.username,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue profile update for user {user.username}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing profile update for user %s",
                    user.username,
                )

        logger.info(
            "Profile update queuing completed: %d queued, %d errors out of %d total users",  # noqa: E501
            updated_count,
            error_count,
            total_users,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Profile update tasks queued",
            "total": total_users,
            "queued": updated_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in auto_update_users_profile")
        return {"success": False, "error": f"Critical error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def auto_update_user_profile(self, user_id):
    """
    Update a specific user's profile from Instagram API if auto-update is enabled.

    Args:
        user_id (str): UUID of the user to update

    Returns:
        dict: Operation result with success status and details
    """
    try:
        user = User.objects.get(uuid=user_id)
    except User.DoesNotExist:
        logger.exception("User with ID %s not found", user_id)
        return {"success": False, "error": "User not found"}

    if not user.allow_auto_update_profile:
        logger.info(
            "Auto-update profile disabled for user %s",
            user.username,
        )
        return {
            "success": False,
            "error": "Auto-update profile not enabled for this user",
            "username": user.username,
        }

    try:
        user.update_profile_from_api()
        logger.info("Successfully updated profile for user: %s", user.username)

        return {  # noqa: TRY300
            "success": True,
            "message": "Profile updated successfully",
            "username": user.username,
        }

    except Exception as e:
        error_msg = str(e)

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error updating profile for %s (attempt %s/%s): %s",
                user.username,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to update profile for user %s after %s attempts",
            user.username,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "username": user.username,
            "attempts": self.request.retries + 1,
        }


@shared_task
def auto_update_users_story():
    """
    Update all users' stories from Instagram API for users with auto-update enabled.
    Uses async story update to queue tasks in Celery.
    Returns summary of operations performed.
    """
    try:
        # Get all users with auto-update stories enabled
        users = User.objects.filter(allow_auto_update_stories=True)
        total_users = users.count()

        if total_users == 0:
            logger.info("No users found with auto-update stories enabled")
            return {
                "success": True,
                "message": "No users to update",
                "queued": 0,
                "errors": 0,
            }

        logger.info("Starting story update for %d users", total_users)

        queued_count = 0
        error_count = 0
        errors = []
        task_ids = []

        for user in users:
            try:
                # Use Celery task to handle each user's story update
                task_result = auto_update_user_story.delay(str(user.uuid))
                task_ids.append(task_result.id)
                queued_count += 1
                logger.info(
                    "Successfully queued story update for user: %s (task: %s)",
                    user.username,
                    task_result.id,
                )
            except Exception as e:
                error_count += 1
                error_msg = (
                    f"Failed to queue story update for user {user.username}: {e!s}"
                )
                errors.append(error_msg)
                logger.exception(
                    "Error queuing story update for user %s",
                    user.username,
                )

        logger.info(
            "Story update queuing completed: %d queued, %d errors"
            " out of %d total users",
            queued_count,
            error_count,
            total_users,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": "Story update tasks queued",
            "total": total_users,
            "queued": queued_count,
            "errors": error_count,
            "error_details": errors if errors else None,
            "task_ids": task_ids,
        }

    except Exception as e:
        logger.exception("Critical error in auto_update_users_story")
        return {"success": False, "error": f"Critical error: {e!s}"}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def auto_update_user_story(self, user_id):
    """
    Update a specific user's stories from Instagram API if auto-update is enabled.

    Args:
        user_id (str): UUID of the user to update

    Returns:
        dict: Operation result with success status and details
    """
    try:
        user = User.objects.get(uuid=user_id)
    except User.DoesNotExist:
        logger.exception("User with ID %s not found", user_id)
        return {"success": False, "error": "User not found"}

    if not user.allow_auto_update_stories:
        logger.info(
            "Auto-update stories disabled for user %s",
            user.username,
        )
        return {
            "success": False,
            "error": "Auto-update stories not enabled for this user",
            "username": user.username,
        }

    try:
        # Use synchronous method to update stories directly
        updated_stories = user.update_stories_from_api()
        stories_count = len(updated_stories) if updated_stories else 0
        logger.info(
            "Successfully updated %d stories for user: %s",
            stories_count,
            user.username,
        )

        return {  # noqa: TRY300
            "success": True,
            "message": f"Successfully updated {stories_count} stories",
            "username": user.username,
            "stories_count": stories_count,
        }

    except Exception as e:
        error_msg = str(e)

        # Handle HTTP 429 (Too Many Requests) with unlimited retries and a delay
        if (
            isinstance(e, requests.exceptions.HTTPError)
            and e.response is not None
            and e.response.status_code == HTTPStatus.TOO_MANY_REQUESTS
        ):
            retry_after = e.response.headers.get("Retry-After")
            countdown = 300  # Default delay: 5 minutes
            with contextlib.suppress(ValueError, TypeError):
                countdown = int(retry_after)
            logger.warning(
                "Rate limit (429) for user %s, retrying in %s seconds (no retry limit)",
                user.username,
                countdown,
            )
            # Re-queue the task with a delay — no retry limit for 429 errors
            self.apply_async(args=[user_id], countdown=countdown)
            return {
                "success": False,
                "error": "Rate limited (429)",
                "username": user.username,
                "retry_in": countdown,
            }

        # Determine if this is a retryable error
        retryable_keywords = [
            "network",
            "timeout",
            "connection",
            "502",
            "503",
            "504",
            "temporary",
            "rate limit",
            "api error",
        ]
        is_retryable = any(
            keyword in error_msg.lower() for keyword in retryable_keywords
        )

        if is_retryable and self.request.retries < self.max_retries:
            logger.warning(
                "Retryable error updating stories for %s (attempt %s/%s): %s",
                user.username,
                self.request.retries + 1,
                self.max_retries + 1,
                error_msg,
            )
            # Exponential backoff
            countdown = 60 * (2**self.request.retries)
            raise self.retry(exc=e, countdown=countdown) from e

        # Non-retryable error or max retries exceeded
        logger.exception(
            "Failed to update stories for user %s after %s attempts",
            user.username,
            self.request.retries + 1,
        )

        return {
            "success": False,
            "error": error_msg,
            "username": user.username,
            "attempts": self.request.retries + 1,
        }
