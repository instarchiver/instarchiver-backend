from django.core.cache import cache
from django.db.models import Count
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from pgvector.django import CosineDistance
from pgvector.django import L2Distance
from rest_framework import filters
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from core.utils.openai import generate_text_embedding
from core.utils.view_tracking import get_client_ip
from core.utils.view_tracking import should_count_view
from instagram.constants import SIMILAR_MAX_COSINE_DISTANCE
from instagram.models import Post
from instagram.models import PostMedia
from instagram.models import Story
from instagram.models import User as InstagramUser
from instagram.paginations import PostAISearchCursorPagination
from instagram.paginations import PostCursorPagination
from instagram.paginations import PostSimilarPageNumberPagination
from instagram.serializers.posts import PostDetailSerializer
from instagram.serializers.posts import PostListSerializer
from instagram.tasks.post import increment_post_view_count


class PostListView(ListAPIView):
    queryset = Post.objects.all().order_by("-created_at")
    serializer_class = PostListSerializer
    pagination_class = PostCursorPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend,
        filters.OrderingFilter,
    ]
    search_fields = ["user__username", "user__full_name", "user__biography", "caption"]
    filterset_fields = ["user", "variant"]
    ordering_fields = ["created_at", "updated_at", "post_created_at"]
    ordering = "-post_created_at"

    def get_queryset(self):
        # Annotate users with has_stories and has_history
        annotated_users = InstagramUser.objects.annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
        )

        # Rows are inserted in carousel order, so id keeps that order
        ordered_postmedia = PostMedia.objects.order_by("id")

        return (
            Post.objects.defer("raw_data", "embedding")
            .prefetch_related(
                Prefetch("user", queryset=annotated_users),
                Prefetch("postmedia_set", queryset=ordered_postmedia),
            )
            .annotate(media_count=Count("postmedia"))
            .order_by("-created_at")
        )


class PostDetailView(RetrieveAPIView):
    queryset = Post.objects.all()
    serializer_class = PostDetailSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "id"

    def get_queryset(self):
        # Annotate users with has_stories and has_history
        annotated_users = InstagramUser.objects.annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
        )

        # Rows are inserted in carousel order, so id keeps that order
        ordered_postmedia = PostMedia.objects.order_by("id")

        return Post.objects.defer("raw_data", "embedding").prefetch_related(
            Prefetch("user", queryset=annotated_users),
            Prefetch("postmedia_set", queryset=ordered_postmedia),
        )

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

        # Annotate users with has_stories and has_history
        annotated_users = InstagramUser.objects.annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
        )

        # Rows are inserted in carousel order, so id keeps that order
        ordered_postmedia = PostMedia.objects.order_by("id")

        # Generate embedding for search query
        query_embedding, _ = generate_text_embedding(search_query)

        # Filter posts with embeddings and order by similarity
        return (
            Post.objects.filter(embedding__isnull=False)
            .defer("raw_data", "embedding")
            .prefetch_related(
                Prefetch("user", queryset=annotated_users),
                Prefetch("postmedia_set", queryset=ordered_postmedia),
            )
            .annotate(
                media_count=Count("postmedia"),
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
    """Posts ranked by cosine distance to a given post within the relevance threshold."""  # noqa: E501

    serializer_class = PostListSerializer
    pagination_class = PostSimilarPageNumberPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    @extend_schema(
        summary="Get similar posts",
        description=(
            "Retrieve posts similar to the specified post based on embedding "
            "cosine distance. Only returns posts that have embeddings within "
            "the similarity threshold."
        ),
        responses={
            200: PostListSerializer(many=True),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Post.objects.none()

        post_id = self.kwargs.get("id")

        # None when the post is missing or has no embedding yet.
        embedding = (
            Post.objects.filter(id=post_id).values_list("embedding", flat=True).first()
        )
        if embedding is None:
            return Post.objects.none()

        # Annotate users with has_stories and has_history
        annotated_users = InstagramUser.objects.annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
        )

        # Rows are inserted in carousel order, so id keeps that order
        ordered_postmedia = PostMedia.objects.order_by("id")

        return (
            Post.objects.filter(embedding__isnull=False)
            .defer("raw_data", "embedding")
            .exclude(id=post_id)
            .alias(distance=CosineDistance("embedding", embedding))
            .filter(distance__lte=SIMILAR_MAX_COSINE_DISTANCE)
            .prefetch_related(
                Prefetch("user", queryset=annotated_users),
                Prefetch("postmedia_set", queryset=ordered_postmedia),
            )
            .annotate(media_count=Count("postmedia"))
            .order_by("distance", "id")
        )
