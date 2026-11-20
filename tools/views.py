from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tools.instagram import InstagramProfileError
from tools.instagram import fetch_instagram_profile

ProfileDetailErrorSerializer = inline_serializer(
    name="ProfileDetailError",
    fields={
        "detail": serializers.CharField(),
        "code": serializers.CharField(required=False),
    },
)


class InstagramProfileDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get Instagram profile detail directly",
        description=(
            "Fetch public Instagram profile details directly from Instagram "
            "without calling SaveAPI."
        ),
        parameters=[
            OpenApiParameter(
                name="username",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Instagram username without @",
            ),
        ],
        responses={
            200: OpenApiTypes.OBJECT,
            400: OpenApiResponse(
                response=ProfileDetailErrorSerializer,
                description="Missing or invalid Instagram username.",
            ),
            401: OpenApiResponse(
                response=ProfileDetailErrorSerializer,
                description="Authentication credentials were not provided.",
            ),
            403: OpenApiResponse(
                response=ProfileDetailErrorSerializer,
                description="Permission denied.",
            ),
            404: OpenApiResponse(
                response=ProfileDetailErrorSerializer,
                description="Instagram profile was not found.",
            ),
            429: OpenApiResponse(
                response=ProfileDetailErrorSerializer,
                description="Instagram rate limited the request.",
            ),
            502: OpenApiResponse(
                response=ProfileDetailErrorSerializer,
                description="Failed to fetch or parse the Instagram profile page.",
            ),
        },
    )
    def get(self, request):
        username = request.query_params.get("username", "")
        try:
            profile = fetch_instagram_profile(username)
        except InstagramProfileError as exc:
            return Response(
                {"detail": exc.message, "code": exc.code},
                status=exc.status_code,
            )

        if profile is None:
            return Response(
                {"detail": "Instagram profile not found.", "code": "NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(profile, status=status.HTTP_200_OK)
