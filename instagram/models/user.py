import hashlib
import logging
import uuid
from urllib.parse import urlparse

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.utils.instagram_api import fetch_user_posts_by_username
from core.utils.saveapi import RETRYABLE_ERROR_CODES
from core.utils.saveapi import SaveAPIError
from core.utils.saveapi import fetch_user_profile
from core.utils.saveapi import fetch_user_stories as fetch_user_stories_from_saveapi
from instagram.constants import PROFILE_DUPLICATE_ACCOUNT
from instagram.constants import PROFILE_ID_MISMATCH
from instagram.misc import get_user_profile_picture_upload_location
from instagram.models.mixins import ViewCountMixin

logger = logging.getLogger(__name__)


class GetUserPostMixIn:
    """Mixin class to add post-related functionality to User model."""

    def get_post_data_from_api(self, max_id: str | None = None):
        """Fetch user posts from Instagram API with pagination support.

        Args:
            max_id: Optional pagination cursor for fetching next page

        Returns:
            tuple: (list of posts, next_max_id or None)
        """
        if not self.instagram_id:
            msg = f"User {self.username} has no Instagram ID"
            raise ValueError(msg)

        response = fetch_user_posts_by_username(self.instagram_id, max_id=max_id)
        data = response.get("data", {})
        items = data.get("items", [])
        next_max_id = data.get("next_max_id")
        logger.info(
            "Fetched %d posts for user %s (next_max_id: %s)",
            len(items),
            self.username,
            next_max_id or "None",
        )
        return items, next_max_id

    def _update_post_data_from_api(self, max_id: str | None = None) -> dict:
        """Fetch and save user posts with pagination support.

        This method recursively fetches all pages of posts using the max_id cursor.

        Args:
            max_id: Optional pagination cursor for fetching next page

        Returns:
            dict: Summary with total_posts, pages_fetched, and last_max_id
        """
        from instagram.models import Post  # noqa: PLC0415

        posts, next_max_id = self.get_post_data_from_api(max_id=max_id)
        posts_saved = 0

        # Save posts from current page
        for post in posts:
            obj, _ = Post.objects.update_or_create(
                id=post.get("pk"),
                user=self,
            )
            obj.raw_data = post
            obj.thumbnail_url = post.get("display_uri")
            obj.caption = post.get("caption").get("text") if post.get("caption") else ""
            # Convert epoch timestamp to timezone-aware datetime
            taken_at = post.get("taken_at")
            if taken_at:
                obj.post_created_at = timezone.datetime.fromtimestamp(
                    taken_at,
                    tz=timezone.get_current_timezone(),
                )
            obj.save()
            posts_saved += 1

        logger.info(
            "Saved %d posts for user %s (current page)",
            posts_saved,
            self.username,
        )

        # If there's a next page, recursively fetch it
        if next_max_id:
            logger.info(
                "Fetching next page for user %s with max_id: %s",
                self.username,
                next_max_id,
            )
            next_result = self._update_post_data_from_api(max_id=next_max_id)
            return {
                "total_posts": posts_saved + next_result["total_posts"],
                "pages_fetched": 1 + next_result["pages_fetched"],
                "last_max_id": next_result["last_max_id"],
            }

        # No more pages, return summary
        return {
            "total_posts": posts_saved,
            "pages_fetched": 1,
            "last_max_id": max_id,
        }

    def update_post_data_from_api(self):
        """Update user posts from Instagram API synchronously.

        Note: This method is deprecated. Use update_posts_from_api_async() instead
        for better performance with pagination support.
        """
        result = self._update_post_data_from_api()
        logger.info(
            "Updated %d posts across %d pages for user %s",
            result["total_posts"],
            result["pages_fetched"],
            self.username,
        )

    def update_posts_from_api_async(self):
        """
        Trigger asynchronous update of user posts from Instagram API.
        Use this method to queue the post update as a background task.
        """
        from instagram.tasks import update_user_posts_from_api  # noqa: PLC0415

        logger.info("Queuing post update task for user %s", self.username)
        return update_user_posts_from_api.delay(self.uuid)


class User(GetUserPostMixIn, ViewCountMixin):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    instagram_id = models.CharField(max_length=50, unique=True, blank=True, null=True)
    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    profile_picture = models.ImageField(
        upload_to=get_user_profile_picture_upload_location,
        blank=True,
        null=True,
        max_length=512,
    )
    original_profile_picture_url = models.URLField(
        max_length=2500,
        blank=True,
        help_text="The original profile picture URL from Instagram",
    )
    biography = models.TextField(blank=True)
    is_private = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    media_count = models.PositiveIntegerField(default=0)
    follower_count = models.PositiveIntegerField(default=0)
    following_count = models.PositiveIntegerField(default=0)
    raw_api_data = models.JSONField(blank=True, null=True)

    allow_auto_update_stories = models.BooleanField(default=False)
    allow_auto_update_profile = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    api_updated_at = models.DateTimeField(
        verbose_name="Updated From API",
        blank=True,
        null=True,
    )
    history = HistoricalRecords()

    def __str__(self):
        return self.username

    def delete(self, *args, **kwargs):
        """Delete the user instance and clean up all historical records."""
        # Delete all historical records for this user
        self.history.all().delete()

        # Call the parent delete method
        return super().delete(*args, **kwargs)

    def _extract_api_data_from_saveapi(self, data):
        """Copy profile fields from a SaveAPI profile response onto this user."""
        if not data:
            return

        instagram_id = data.get("id")
        self.instagram_id = str(instagram_id) if instagram_id else self.instagram_id
        self.username = data.get("username") or self.username
        self.full_name = data.get("full_name") or ""
        self.original_profile_picture_url = (
            data.get("profile_pic_url_hd") or data.get("profile_pic_url") or ""
        )
        self.biography = data.get("biography") or ""
        self.is_private = bool(data.get("is_private"))
        self.is_verified = bool(data.get("is_verified"))
        self.media_count = data.get("posts") or 0
        self.follower_count = data.get("followers") or 0
        self.following_count = data.get("following") or 0

    def _check_profile_conflicts(self, data):
        """Raise SaveAPIError if saving this profile would clash with stored data.

        SaveAPI looks profiles up by username only. When a username now belongs
        to a different account, the returned id won't match the stored one, and
        saving it would overwrite the old account's record. A returned id or
        username already used by another row would break the unique constraints.
        """
        instagram_id = str(data["id"]) if data.get("id") else None
        username = data.get("username")

        if self.instagram_id and instagram_id and instagram_id != self.instagram_id:
            msg = (
                f"username {self.username} now belongs to Instagram id "
                f"{instagram_id}, not {self.instagram_id}"
            )
            raise SaveAPIError(PROFILE_ID_MISMATCH, msg)

        others = User.objects.exclude(pk=self.pk)
        if instagram_id and others.filter(instagram_id=instagram_id).exists():
            msg = f"Instagram id {instagram_id} is already stored on another user"
            raise SaveAPIError(PROFILE_DUPLICATE_ACCOUNT, msg)
        if (
            username
            and username != self.username
            and others.filter(username=username).exists()
        ):
            msg = f"username {username} is already stored on another user"
            raise SaveAPIError(PROFILE_DUPLICATE_ACCOUNT, msg)

    def update_profile_from_api(self):
        """Update the user profile from SaveAPI, looked up by username."""
        response = fetch_user_profile(self.username)

        if not response.get("success"):
            error = response.get("error") or {}
            code = error.get("code") or "UNKNOWN"
            error_exc = SaveAPIError(
                code,
                error.get("message") or "no error message",
                retryable=code in RETRYABLE_ERROR_CODES,
            )
            logger.error(
                "Error fetching profile for user %s. %s",
                self.username,
                error_exc,
            )
            raise error_exc

        self._check_profile_conflicts(response)

        # recent_posts holds signed URLs that change on every request, which
        # would bloat the history table, and credits is billing data.
        self.raw_api_data = {
            key: value
            for key, value in response.items()
            if key not in {"credits", "recent_posts"}
        }
        self._extract_api_data_from_saveapi(response)
        self.api_updated_at = timezone.now()
        self.save()

    def _update_stories_from_saveapi(self):
        """Update user stories from SaveAPI and record the run in UserUpdateStoryLog.

        SaveAPI does not return story IDs or timestamps. The story ID is a SHA-1
        of the media URL path (the query string holds signatures that change on
        every request), and story_created_at is the fetch time. Video items have
        no thumbnail; one is generated from the video after it is stored.
        """
        # Import here to avoid circular imports
        from .story import Story  # noqa: PLC0415
        from .story import UserUpdateStoryLog  # noqa: PLC0415

        log_entry = UserUpdateStoryLog.objects.create(
            user=self,
            status=UserUpdateStoryLog.STATUS_IN_PROGRESS,
            message="Started story update from SaveAPI",
        )

        try:
            response = fetch_user_stories_from_saveapi(self.username)

            if not response.get("success"):
                error = response.get("error") or {}
                code = error.get("code") or "UNKNOWN"
                error_exc = SaveAPIError(
                    code,
                    error.get("message") or "no error message",
                    retryable=code in RETRYABLE_ERROR_CODES,
                )
                msg = f"Error fetching stories for user {self.username}. {error_exc}"
                logger.error(msg)

                log_entry.status = UserUpdateStoryLog.STATUS_FAILED
                log_entry.message = msg
                log_entry.save()

                raise error_exc  # noqa: TRY301

            updated_stories = []
            fetched_at = timezone.now()

            for media in response.get("medias") or []:
                media_url = media.get("url")
                if not media_url:
                    continue

                story_id = hashlib.sha1(  # noqa: S324
                    urlparse(media_url).path.encode(),
                ).hexdigest()
                is_image = media.get("type") == "image"

                story, _ = Story.objects.get_or_create(
                    story_id=story_id,
                    defaults={
                        "user": self,
                        "thumbnail_url": media_url if is_image else "",
                        "media_url": media_url,
                        "story_created_at": fetched_at,
                        "raw_api_data": media,
                    },
                )
                updated_stories.append(story)

            log_entry.status = UserUpdateStoryLog.STATUS_COMPLETED
            log_entry.message = (
                f"Successfully updated {len(updated_stories)} stories from SaveAPI"
            )
            log_entry.save()

            logger.info(
                "Successfully updated %d stories from SaveAPI for user %s",
                len(updated_stories),
                self.username,
            )
            return updated_stories  # noqa: TRY300

        except Exception as e:
            if log_entry.status == UserUpdateStoryLog.STATUS_IN_PROGRESS:
                log_entry.status = UserUpdateStoryLog.STATUS_FAILED
                log_entry.message = str(e)
                log_entry.save()

            logger.exception(
                "Failed to update stories from SaveAPI for user %s: %s",
                self.username,
                e,  # noqa: TRY401
            )
            raise

    def update_stories_from_saveapi(self):
        """Update user stories from SaveAPI synchronously."""
        return self._update_stories_from_saveapi()

    def update_stories_from_saveapi_async(self):
        """Queue a background task that updates user stories from SaveAPI."""
        from instagram.tasks import update_user_stories_from_saveapi  # noqa: PLC0415

        logger.info("Queuing SaveAPI story update task for user %s", self.username)
        return update_user_stories_from_saveapi.delay(self.uuid)
