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

from core.utils.view_tracking import get_client_ip
from core.utils.view_tracking import should_count_view
from instagram.constants import DETAIL_USER_DEFERRED
from instagram.constants import LIST_USER_DEFERRED
from instagram.constants import STORY_FIELDS
from instagram.models import Story
from instagram.models import User as InstagramUser
from instagram.paginations import SimilarPagination
from instagram.paginations import StoryCursorPagination
from instagram.serializers.stories import StoryDetailSerializer
from instagram.serializers.stories import StoryListSerializer
from instagram.tasks.story import increment_story_view_count
from instagram.views.mixins import CachedListMixin


def _annotated_users():
    """Instagram users annotated with has_stories and has_history.

    Returns:
        QuerySet: InstagramUser queryset for prefetching story.user
    """
    return InstagramUser.objects.annotate(
        has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
        has_history=Exists(
            InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
        ),
    )


class StoryListView(CachedListMixin, ListAPIView):
    cache_prefix = "story_list"
    serializer_class = StoryListSerializer
    pagination_class = StoryCursorPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    filter_backends = [filters.SearchFilter, DjangoFilterBackend]
    search_fields = ["user__username", "user__full_name", "user__biography"]
    filterset_fields = ["user"]

    def get_queryset(self):
        users = _annotated_users().defer(*LIST_USER_DEFERRED)
        return (
            Story.objects.only(*STORY_FIELDS)
            .prefetch_related(Prefetch("user", queryset=users))
            .order_by("-created_at")
        )


class StoryDetailView(RetrieveAPIView):
    serializer_class = StoryDetailSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "story_id"

    def get_queryset(self):
        users = _annotated_users().defer(*DETAIL_USER_DEFERRED)
        return Story.objects.only(*STORY_FIELDS).prefetch_related(
            Prefetch("user", queryset=users),
        )

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        story_id = kwargs.get(self.lookup_field)
        if should_count_view("story", story_id, get_client_ip(request)):
            increment_story_view_count.delay(story_id)
        return response


class StorySimilarView(ListAPIView):
    """Stories ranked by embedding similarity (L2Distance) to a given story."""

    serializer_class = StoryListSerializer
    pagination_class = SimilarPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    @extend_schema(
        summary="Get similar stories",
        description=(
            "Retrieve stories similar to the specified story based on embedding "
            "similarity using L2Distance. Only returns stories that have embeddings."
        ),
        responses={
            200: StoryListSerializer(many=True),
            404: OpenApiResponse(description="Invalid or out-of-range page"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        story_id = self.kwargs.get("story_id")
        # None when the story is missing or has no embedding yet.
        embedding = (
            Story.objects.filter(story_id=story_id)
            .values_list("embedding", flat=True)
            .first()
        )
        if embedding is None:
            return Story.objects.none()

        users = _annotated_users().defer(*LIST_USER_DEFERRED)
        return (
            Story.objects.filter(embedding__isnull=False)
            .exclude(story_id=story_id)
            .only(*STORY_FIELDS)
            .prefetch_related(Prefetch("user", queryset=users))
            .order_by(L2Distance("embedding", embedding), "story_id")
        )
