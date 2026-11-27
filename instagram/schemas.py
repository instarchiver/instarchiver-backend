from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema

from instagram.serializers.posts import PostArchiveSerializer
from instagram.serializers.posts import PostDetailSerializer

post_archive_schema = extend_schema(
    summary="Archive an Instagram post",
    description=(
        "Fetch an Instagram post or reel from SaveAPI by URL and store it "
        "in the archive. Returns 201 when newly archived or 200 if already saved."
    ),
    request=PostArchiveSerializer,
    responses={
        200: PostDetailSerializer,
        201: PostDetailSerializer,
        400: OpenApiResponse(description="Invalid Instagram post URL"),
        403: OpenApiResponse(description="Authentication required"),
        404: OpenApiResponse(description="Instagram post not found or private"),
        429: OpenApiResponse(
            description="Daily archive limit or upstream rate limit",
        ),
        502: OpenApiResponse(description="Upstream service error"),
        503: OpenApiResponse(description="Post archiving service not configured"),
        504: OpenApiResponse(description="Upstream service timed out"),
    },
)
