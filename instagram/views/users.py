from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import filters
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.generics import ListCreateAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView

from instagram.models import Story
from instagram.models import User as InstagramUser
from instagram.models import UserFollow
from instagram.paginations import InstagramUserCursorPagination
from instagram.paginations import InstagramUserHistoryCursorPagination
from instagram.paginations import UserFollowCursorPagination
from instagram.serializers.user_follows import UserFollowSerializer
from instagram.serializers.users import CreateInstagramUserStoryCreditSerializer
from instagram.serializers.users import InstagramUserCreateSerializer
from instagram.serializers.users import InstagramUserDetailSerializer
from instagram.serializers.users import InstagramUserHistoryListSerializer
from instagram.serializers.users import InstagramUserListSerializer
from payments.utils import stripe_create_instagram_user_story_credits_payment

CACHE_TTL = 60 * 5  # 5 minutes


class InstagramUserListCreateView(ListCreateAPIView):
    queryset = InstagramUser.objects.all().order_by("-created_at")
    serializer_class = InstagramUserListSerializer
    pagination_class = InstagramUserCursorPagination
    permission_classes = [IsAuthenticatedOrReadOnly]

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["username", "full_name", "biography"]
    ordering_fields = ["created_at", "updated_at", "username", "full_name"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        """Use different serializers for list and create actions."""
        if self.request.method == "POST":
            return InstagramUserCreateSerializer
        return InstagramUserListSerializer

    def get_queryset(self):
        return (
            InstagramUser.objects.all()
            .prefetch_related("story_set")
            .annotate(
                has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
                has_history=Exists(
                    InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
                ),
            )
        )

    def create(self, request, *args, **kwargs):
        # Check rate limit: max 3 users created in last 24 hours
        time_threshold = timezone.localdate() - timedelta(days=1)
        max_creations_per_day = 3

        # Count Instagram users created by this user in the last 24 hours
        # Only count creation events for users that still exist (not deleted)
        # Get UUIDs of users created in the last 24 hours
        created_user_uuids = InstagramUser.history.filter(
            Q(history_user=request.user)
            & Q(history_date__gte=time_threshold)
            & Q(history_type="+"),  # "+" indicates creation
        ).values_list("uuid", flat=True)

        # Filter to only include UUIDs that still exist in the current table
        recent_creations = InstagramUser.objects.filter(
            uuid__in=created_user_uuids,
        ).count()

        if recent_creations >= max_creations_per_day:
            return Response(
                {
                    "detail": (
                        f"You have reached the limit of {max_creations_per_day} user creations "  # noqa: E501
                        "in the last 24 hours. Please try again later."
                    ),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                serializer.save()
        except Exception as e:  # noqa: BLE001
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Use user detail serializer to return the created user
        serializer = InstagramUserDetailSerializer(serializer.instance)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class InstagramUserDetailView(RetrieveAPIView):
    queryset = InstagramUser.objects.all()
    serializer_class = InstagramUserDetailSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "uuid"
    filter_backends = [filters.SearchFilter]
    search_fields = ["full_name", "username", "biography"]

    def get_queryset(self):
        return (
            InstagramUser.objects.all()
            .prefetch_related("story_set")
            .annotate(
                has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
                has_history=Exists(
                    InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
                ),
            )
        )


class InstagramUserHistoryView(ListAPIView):
    serializer_class = InstagramUserHistoryListSerializer
    pagination_class = InstagramUserHistoryCursorPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "uuid"

    def get_queryset(self):
        uuid = self.kwargs.get("uuid")
        return InstagramUser.history.filter(uuid=uuid).order_by("-history_date")


class InstagramUserAddStoryCreditAPIView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CreateInstagramUserStoryCreditSerializer

    def post(self, request, uuid):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        instagram_user = InstagramUser.objects.get(uuid=uuid)

        _ = stripe_create_instagram_user_story_credits_payment(
            user_id=user.id,
            instagram_user_id=instagram_user.pk,
            story_credit_quantity=serializer.validated_data["story_credit"],
        )

        return Response({"detail": "Payment created successfully."})


class _UserFollowBaseListView(ListAPIView):
    """Base view for followers/following list endpoints."""

    serializer_class = UserFollowSerializer
    pagination_class = UserFollowCursorPagination
    permission_classes = [IsAuthenticatedOrReadOnly]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["follower__username", "follower__full_name"]
    ordering_fields = ["first_seen_at", "follower__username"]
    ordering = ["-first_seen_at"]

    # Set by subclass
    relationship = None

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["relationship"] = self.relationship
        return ctx

    def get(self, request, *args, **kwargs):
        cache_key = f"user_follow:{kwargs['uuid']}:{self.relationship}:{request.query_params.urlencode()}"  # noqa: E501
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().get(request, *args, **kwargs)
        cache.set(cache_key, response.data, timeout=CACHE_TTL)
        return response


class InstagramUserFollowersView(_UserFollowBaseListView):
    """
    List all active followers of an Instagram user.

    Supports:
    - ?is_mutual=true — filter to mutual followers only
    - ?search= — filter by follower username or full name
    - ?ordering= — order by first_seen_at or follower__username
    """

    relationship = "followers"
    search_fields = ["follower__username", "follower__full_name"]
    ordering_fields = ["first_seen_at", "follower__username"]

    def get_queryset(self):
        instagram_user = get_object_or_404(InstagramUser, uuid=self.kwargs["uuid"])
        queryset = (
            UserFollow.objects.filter(following=instagram_user, is_active=True)
            .select_related("follower")
            .annotate(
                is_mutual=Exists(
                    UserFollow.objects.filter(
                        follower=instagram_user,
                        following=OuterRef("follower"),
                        is_active=True,
                    ),
                ),
            )
        )
        is_mutual = self.request.query_params.get("is_mutual")
        if is_mutual and is_mutual.lower() == "true":
            queryset = queryset.filter(is_mutual=True)
        return queryset


class InstagramUserFollowingView(_UserFollowBaseListView):
    """
    List all accounts that an Instagram user actively follows.

    Supports:
    - ?is_mutual=true — filter to mutual following only
    - ?search= — filter by following username or full name
    - ?ordering= — order by first_seen_at or following__username
    """

    relationship = "following"
    search_fields = ["following__username", "following__full_name"]
    ordering_fields = ["first_seen_at", "following__username"]

    def get_queryset(self):
        instagram_user = get_object_or_404(InstagramUser, uuid=self.kwargs["uuid"])
        queryset = (
            UserFollow.objects.filter(follower=instagram_user, is_active=True)
            .select_related("following")
            .annotate(
                is_mutual=Exists(
                    UserFollow.objects.filter(
                        following=instagram_user,
                        follower=OuterRef("following"),
                        is_active=True,
                    ),
                ),
            )
        )
        is_mutual = self.request.query_params.get("is_mutual")
        if is_mutual and is_mutual.lower() == "true":
            queryset = queryset.filter(is_mutual=True)
        return queryset
