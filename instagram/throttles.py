from rest_framework.throttling import UserRateThrottle


class PostArchiveRateThrottle(UserRateThrottle):
    """Per-user daily request cap to prevent repeated SaveAPI credit drain."""

    scope = "post_archive"

    def get_rate(self):
        return "200/day"
