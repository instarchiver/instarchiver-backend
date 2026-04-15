from django.db import models


class UserFollow(models.Model):
    """
    Represents a follow relationship between two Instagram users.
    Read as: "follower follows following".
    """

    follower = models.ForeignKey(
        "instagram.User",
        on_delete=models.CASCADE,
        related_name="following_set",
    )
    following = models.ForeignKey(
        "instagram.User",
        on_delete=models.CASCADE,
        related_name="follower_set",
    )
    is_active = models.BooleanField(default=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("follower", "following")
        indexes = [
            models.Index(fields=["follower", "is_active"]),
            models.Index(fields=["following", "is_active"]),
        ]

    def __str__(self):
        return f"{self.follower_id} -> {self.following_id}"
