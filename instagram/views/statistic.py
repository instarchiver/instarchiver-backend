from django.core.cache import cache
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from instagram.models import Post
from instagram.models import Story
from instagram.models.user import User as InstagramUser

CACHE_KEY = "instagram_statistic"
CACHE_TTL = 60 * 30  # 30 minutes


class InstagramStatisticView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            return Response(cached)

        data = {
            "total_users": InstagramUser.objects.count(),
            "total_stories": Story.objects.count(),
            "total_posts": Post.objects.count(),
        }
        cache.set(CACHE_KEY, data, CACHE_TTL)
        return Response(data)
