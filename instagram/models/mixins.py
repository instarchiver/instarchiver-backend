from django.db import models


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
