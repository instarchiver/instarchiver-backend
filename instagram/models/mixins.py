from django.db import models


class UserFollowMixin:
    """Mixin class to add follower/following sync functionality to the Instagram User model."""  # noqa: E501

    def sync_followers(self, followers_data: list[dict]) -> None:
        """
        Sync followers from a list of dicts (from API response).
        Expected item format: {'id': str, 'username': str, 'full_name': str,
                               'is_private': bool, 'is_verified': bool}

        Auto-creates instagram.User for followers not yet in the system.
        Sets is_active=False for relationships no longer present in the data.
        """
        from instagram.models.user import User  # noqa: PLC0415
        from instagram.models.user_follow import UserFollow  # noqa: PLC0415

        seen_pks = []
        for data in followers_data:
            instagram_id = str(data["id"])
            user, _ = User.objects.get_or_create(
                instagram_id=instagram_id,
                defaults={
                    "username": data["username"],
                    "full_name": data.get("full_name", ""),
                    "is_private": data.get("is_private", False),
                    "is_verified": data.get("is_verified", False),
                },
            )
            UserFollow.objects.update_or_create(
                follower=user,
                following=self,
                defaults={"is_active": True},
            )
            seen_pks.append(user.pk)

        UserFollow.objects.filter(
            following=self,
            is_active=True,
        ).exclude(follower__in=seen_pks).update(is_active=False)

    def sync_following(self, following_data: list[dict]) -> None:
        """
        Sync following from a list of dicts (from API response).
        Expected item format: {'id': str, 'username': str, 'full_name': str,
                               'is_private': bool, 'is_verified': bool}

        Auto-creates instagram.User for following not yet in the system.
        Sets is_active=False for relationships no longer present in the data.
        """
        from instagram.models.user import User  # noqa: PLC0415
        from instagram.models.user_follow import UserFollow  # noqa: PLC0415

        seen_pks = []
        for data in following_data:
            instagram_id = str(data["id"])
            user, _ = User.objects.get_or_create(
                instagram_id=instagram_id,
                defaults={
                    "username": data["username"],
                    "full_name": data.get("full_name", ""),
                    "is_private": data.get("is_private", False),
                    "is_verified": data.get("is_verified", False),
                },
            )
            UserFollow.objects.update_or_create(
                follower=self,
                following=user,
                defaults={"is_active": True},
            )
            seen_pks.append(user.pk)

        UserFollow.objects.filter(
            follower=self,
            is_active=True,
        ).exclude(following__in=seen_pks).update(is_active=False)


class InstagramModerationMixin(models.Model):
    """
    Mixin to add moderation fields to a model.
    """

    is_flagged = models.BooleanField(default=False)
    moderation_result = models.JSONField(null=True, blank=True)
    moderated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"Flagged: {self.is_flagged}, Moderated At: {self.moderated_at}"

    def moderate_content(self):
        msg = "Subclasses must implement the moderate_content method."
        raise NotImplementedError(msg)
