from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from drf_spectacular.utils import inline_serializer
from rest_framework import serializers

ProfileDetailErrorSerializer = inline_serializer(
    name="ProfileDetailError",
    fields={
        "detail": serializers.CharField(),
        "code": serializers.CharField(required=False),
    },
)

instagram_profile_detail_schema = extend_schema(
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
