from datetime import timedelta

from django.db import transaction
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q
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

from core.utils.view_tracking import get_client_ip
from core.utils.view_tracking import should_count_view
from instagram.models import Story
from instagram.models import User as InstagramUser
from instagram.paginations import InstagramUserCursorPagination
from instagram.paginations import InstagramUserHistoryCursorPagination
from instagram.serializers.users import CreateInstagramUserStoryCreditSerializer
from instagram.serializers.users import InstagramUserCreateSerializer
from instagram.serializers.users import InstagramUserDetailSerializer
from instagram.serializers.users import InstagramUserHistoryListSerializer
from instagram.serializers.users import InstagramUserListSerializer
from instagram.tasks.user import increment_user_view_count
from payments.utils import stripe_create_instagram_user_story_credits_payment


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
        return InstagramUser.objects.all().annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
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
        return InstagramUser.objects.all().annotate(
            has_stories=Exists(Story.objects.filter(user=OuterRef("pk"))),
            has_history=Exists(
                InstagramUser.history.model.objects.filter(uuid=OuterRef("pk")),
            ),
        )

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        user_uuid = kwargs.get(self.lookup_field)
        if should_count_view("user", user_uuid, get_client_ip(request)):
            increment_user_view_count.delay(str(user_uuid))
        return response


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
