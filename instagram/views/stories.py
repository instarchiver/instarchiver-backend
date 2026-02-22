import hashlib
import json

from django.core.cache import cache
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from pgvector.django import L2Distance
from rest_framework import filters
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from instagram.models import Story
from instagram.models import User as InstagramUser
from instagram.paginations import StoryCursorPagination
from instagram.paginations import StorySimilarPageNumberPagination
from instagram.serializers.stories import StoryDetailSerializer
from instagram.serializers.stories import StoryListSerializer


class StoryListView(ListAPIView):
    queryset = Story.objects.all().order_by("-created_at")
    serializer_class = StoryListSerializer
    pagination_class = StoryCursorPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["user__username", "user__full_name", "user__biography"]
    filterset_fields = ["user"]

    def get_queryset(self):
        # Annotate users with has_stories and has_history
        annotated_users = InstagramUser.objects.annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
        )

        return (
            Story.objects.all()
            .prefetch_related(
                Prefetch("user", queryset=annotated_users),
            )
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        """List stories with 30-second caching per unique query parameter combination."""
        params = dict(request.query_params)
        params_key = json.dumps(sorted(params.items()), sort_keys=True)
        cache_key = f"story_list_{hashlib.md5(params_key.encode()).hexdigest()}"

        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, 30)
        return response


class StoryDetailView(RetrieveAPIView):
    queryset = Story.objects.all()
    serializer_class = StoryDetailSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "story_id"

    def get_queryset(self):
        # Annotate users with has_stories and has_history
        annotated_users = InstagramUser.objects.annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
        )

        return Story.objects.all().prefetch_related(
            Prefetch("user", queryset=annotated_users),
        )


class StorySimilarView(ListAPIView):
    """Get similar stories based on embedding similarity using L2Distance."""

    serializer_class = StoryListSerializer
    pagination_class = StorySimilarPageNumberPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    @extend_schema(
        summary="Get similar stories",
        description=(
            "Retrieve stories similar to the specified story based on embedding "
            "similarity using L2Distance. Only returns stories that have embeddings."
        ),
        responses={
            200: StoryListSerializer(many=True),
            404: OpenApiResponse(description="Story not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        # Get the story ID from URL parameter
        story_id = self.kwargs.get("story_id")

        # Get the source story and its embedding
        try:
            source_story = Story.objects.get(story_id=story_id)
        except Story.DoesNotExist:
            return Story.objects.none()

        # If source story has no embedding, return empty queryset
        if source_story.embedding is None:
            return Story.objects.none()

        # Annotate users with has_stories and has_history
        annotated_users = InstagramUser.objects.annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
        )

        # Find similar stories using L2Distance
        return (
            Story.objects.filter(embedding__isnull=False)
            .exclude(story_id=story_id)  # Exclude the source story itself
            .prefetch_related(
                Prefetch("user", queryset=annotated_users),
            )
            .annotate(
                similarity_score=1 - L2Distance("embedding", source_story.embedding),
            )
            .order_by("-similarity_score")
        )
