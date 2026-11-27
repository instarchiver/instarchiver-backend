import logging
from datetime import timedelta

import requests
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from pgvector.django import L2Distance
from rest_framework import filters
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from core.utils.openai import generate_text_embedding
from core.utils.saveapi import SaveAPIError
from core.utils.view_tracking import get_client_ip
from core.utils.view_tracking import should_count_view
from instagram.models import Post
from instagram.paginations import PostAISearchCursorPagination
from instagram.paginations import PostCursorPagination
from instagram.paginations import PostSimilarPageNumberPagination
from instagram.schemas import post_archive_schema
from instagram.serializers.posts import PostArchiveSerializer
from instagram.serializers.posts import PostDetailSerializer
from instagram.serializers.posts import PostListSerializer
from instagram.tasks.post import increment_post_view_count
from instagram.throttles import PostArchiveRateThrottle
from instagram.views.mixins import CachedListMixin

logger = logging.getLogger(__name__)


class PostListView(CachedListMixin, ListCreateAPIView):
    cache_prefix = "post_list"
    queryset = Post.objects.all().order_by("-created_at")
    serializer_class = PostListSerializer
    pagination_class = PostCursorPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    MAX_POST_ARCHIVES_PER_DAY = 100

    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        filters.OrderingFilter,
    ]
    search_fields = ["user__username", "user__full_name", "user__biography", "caption"]
    filterset_fields = ["user", "variant"]
    ordering_fields = ["created_at", "updated_at", "post_created_at"]
    ordering = "-post_created_at"

    def get_serializer_class(self):
        """Use PostArchiveSerializer for POST and PostListSerializer for GET."""
        if self.request.method == "POST":
            return PostArchiveSerializer
        return PostListSerializer

    def get_throttles(self):
        """Apply archive rate throttle to POST requests only."""
        if self.request.method == "POST":
            return [PostArchiveRateThrottle()]
        return []

    def get_queryset(self):
        return Post.detail_queryset().order_by("-created_at")

    @post_archive_schema
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        time_threshold = timezone.now() - timedelta(hours=24)
        archived_post_ids = Post.history.filter(
            Q(history_user=request.user)
            & Q(history_date__gte=time_threshold)
            & Q(history_type="+"),
        ).values_list("id", flat=True)
        recent_archives = Post.objects.filter(id__in=archived_post_ids).count()

        if recent_archives >= self.MAX_POST_ARCHIVES_PER_DAY:
            limit = self.MAX_POST_ARCHIVES_PER_DAY
            return Response(
                {
                    "detail": (
                        f"You have reached the limit of {limit} post archives "
                        "in the last 24 hours. Please try again later."
                    ),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._archive_from_url_response(
            request,
            serializer.validated_data["url"],
        )

    def _archive_from_url_response(self, request, url: str) -> Response:
        try:
            post, created = Post.archive_from_url(url)
        except ImproperlyConfigured:
            logger.exception("SaveAPI configuration missing during post archive")
            return Response(
                {"detail": "Post archiving service is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except SaveAPIError as exc:
            return self._error_response_for_saveapi(exc)
        except requests.Timeout:
            logger.warning("SaveAPI timed out while archiving post")
            return Response(
                {"detail": "Upstream service timed out. Please try again."},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except requests.RequestException:
            logger.exception("Network error calling SaveAPI during post archive")
            return Response(
                {"detail": "Failed to reach upstream service."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except (AttributeError, TypeError, ValueError, DatabaseError):
            logger.exception("Invalid response or database error during post archive")
            return Response(
                {"detail": "Received an invalid post response from upstream service."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        loaded_post = Post.detail_queryset().get(pk=post.pk)
        data = PostDetailSerializer(loaded_post, context={"request": request}).data
        return Response(
            data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @staticmethod
    def _error_response_for_saveapi(exc: SaveAPIError) -> Response:
        if exc.is_rate_limited:
            headers = (
                {"Retry-After": str(exc.retry_after)}
                if exc.retry_after is not None
                else None
            )
            return Response(
                {"detail": "Upstream service is rate limited. Please try again later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers=headers,
            )
        if exc.status_code == status.HTTP_404_NOT_FOUND or exc.code == "NOT_FOUND":
            return Response(
                {"detail": "Instagram post not found or is private."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if exc.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) or exc.code in ("INVALID_URL", "UNSUPPORTED_URL"):
            return Response(
                {"detail": "Invalid or unsupported Instagram post URL."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        logger.warning("SaveAPI returned error %s during post archive", exc.code)
        return Response(
            {"detail": "Failed to fetch post from upstream service."},
            status=status.HTTP_502_BAD_GATEWAY,
        )


class PostDetailView(RetrieveAPIView):
    queryset = Post.objects.all()
    serializer_class = PostDetailSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "id"

    def get_queryset(self):
        return Post.detail_queryset()

    def retrieve(self, request, *args, **kwargs):
        """Retrieve post detail with 30-second caching."""
        post_id = kwargs.get(self.lookup_field)
        cache_key = f"post_detail_{post_id}"

        # Try to get cached response
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            if should_count_view("post", post_id, get_client_ip(request)):
                increment_post_view_count.delay(post_id)
            return Response(cached_response)

        # Get the post instance
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data

        # Cache the response for 30 seconds
        cache.set(cache_key, data, 30)

        if should_count_view("post", post_id, get_client_ip(request)):
            increment_post_view_count.delay(post_id)

        return Response(data)


class PostAISearchView(ListAPIView):
    """AI-powered semantic search endpoint for posts using embeddings."""

    serializer_class = PostListSerializer
    pagination_class = PostAISearchCursorPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        # Get search query from request
        search_query = self.request.query_params.get("text", "").strip()

        if not search_query:
            # Return empty queryset if no search query provided
            return Post.objects.none()

        # Generate embedding for search query
        query_embedding, _ = generate_text_embedding(search_query)

        # Filter posts with embeddings and order by similarity
        return (
            Post.detail_queryset()
            .filter(embedding__isnull=False)
            .annotate(
                similarity_score=1 - L2Distance("embedding", query_embedding),
            )
            .order_by("-similarity_score")
        )

    def get(self, request, *args, **kwargs):
        if not self.request.query_params.get("text"):
            return Response(
                {"error": "Text parameter is required"},
                status=400,
            )

        return super().get(request, *args, **kwargs)


class PostSimilarView(ListAPIView):
    """Get similar posts based on embedding similarity using L2Distance."""

    serializer_class = PostListSerializer
    pagination_class = PostSimilarPageNumberPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    @extend_schema(
        summary="Get similar posts",
        description=(
            "Retrieve posts similar to the specified post based on embedding "
            "similarity using L2Distance. Only returns posts that have embeddings."
        ),
        responses={
            200: PostListSerializer(many=True),
            404: OpenApiResponse(description="Post not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        # Get the post ID from URL parameter
        post_id = self.kwargs.get("id")

        # Get the source post and its embedding
        try:
            source_post = Post.objects.get(id=post_id)
        except Post.DoesNotExist:
            return Post.objects.none()

        # If source post has no embedding, return empty queryset
        if source_post.embedding is None:
            return Post.objects.none()

        # Find similar posts using L2Distance
        return (
            Post.detail_queryset()
            .filter(embedding__isnull=False)
            .exclude(id=post_id)  # Exclude the source post itself
            .annotate(
                similarity_score=1 - L2Distance("embedding", source_post.embedding),
            )
            .order_by("-similarity_score")
        )
