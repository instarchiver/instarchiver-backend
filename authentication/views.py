import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from authentication import firebase

from .serializers import LoginWithGoogleSerializer
from .serializers import RefreshTokenSerializer
from .serializers import UserSerializer

User = get_user_model()
logger = logging.getLogger(__name__)


def _user_field_max_length(field_name: str, default: int) -> int:
    field = User._meta.get_field(field_name)  # noqa: SLF001
    max_length = getattr(field, "max_length", None)
    return max_length if isinstance(max_length, int) else default


EMAIL_MAX_LENGTH = _user_field_max_length("email", 254)
USERNAME_MAX_LENGTH = _user_field_max_length("username", 150)
NAME_MAX_LENGTH = _user_field_max_length("name", 255)
PHOTO_URL_MAX_LENGTH = _user_field_max_length("photo_url", 255)


def _extract_google_user_claims(
    user_info: dict[str, Any],
) -> tuple[dict[str, str] | None, str | None]:
    if user_info.get("email_verified") is not True:
        return None, "Email address is not verified"

    raw_email = user_info.get("email")
    email = raw_email.strip() if isinstance(raw_email, str) else ""
    if not email or len(email) > EMAIL_MAX_LENGTH:
        return None, "Invalid or missing email in token"

    raw_name = user_info.get("name")
    name = raw_name.strip()[:NAME_MAX_LENGTH] if isinstance(raw_name, str) else ""

    raw_photo_url = user_info.get("photo_url")
    candidate_photo = raw_photo_url.strip() if isinstance(raw_photo_url, str) else ""
    photo_url = candidate_photo if len(candidate_photo) <= PHOTO_URL_MAX_LENGTH else ""

    return {"email": email, "name": name, "photo_url": photo_url}, None


class RefreshTokenView(APIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = RefreshTokenSerializer

    @extend_schema(
        summary="Refresh JWT token",
        description="Refreshes the JWT token using the refresh token.",
        responses={
            200: OpenApiResponse(
                description="New JWT tokens",
            ),
        },
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        refresh = serializer.validated_data.get("refresh")
        try:
            token = RefreshToken(refresh)
        except Exception:  # noqa: BLE001
            return Response(
                {"error": "Invalid refresh token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "refresh": str(token),
                "access": str(token.access_token),
            },
        )


class ValidateTokenView(APIView):
    @extend_schema(
        summary="Validate JWT token",
        description="Validates the JWT token and returns user information.",
        responses={
            200: OpenApiResponse(),
        },
    )
    def post(self, request):
        user = request.user
        if not user.is_authenticated:
            return Response(
                {"error": "Invalid token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        return Response(
            {
                "detail": "Token is valid",
            },
            status=status.HTTP_200_OK,
        )


class LoginWithGoogleView(APIView):
    serializer_class = LoginWithGoogleSerializer
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        summary="Login with Google",
        description="Login a user using Google authentication.",
        request=LoginWithGoogleSerializer,
        responses={
            200: OpenApiResponse(
                description="User JWT tokens",
            ),
        },
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data.get("token")

        try:
            user_info = firebase.get_user_info(token)
        except Exception:
            logger.exception("Firebase authentication failed")
            return Response(
                {
                    "error": "Authentication failed",
                    "detail": "Invalid or expired token",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        claims, error_detail = _extract_google_user_claims(user_info)
        if claims is None:
            return Response(
                {
                    "error": "Authentication failed",
                    "detail": error_detail,
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )

        email = claims["email"]
        name = claims["name"]
        photo_url = claims["photo_url"]

        with transaction.atomic():
            try:
                user = User.objects.get(email=email)
                created = False
            except User.DoesNotExist:
                if len(email) > USERNAME_MAX_LENGTH:
                    return Response(
                        {
                            "error": "Authentication failed",
                            "detail": "Email exceeds maximum supported length",
                        },
                        status=status.HTTP_401_UNAUTHORIZED,
                    )
                user, created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        "username": email,
                        "name": name,
                        "photo_url": photo_url,
                    },
                )

            if not created:
                update_fields = []
                if name and user.name != name:
                    user.name = name
                    update_fields.append("name")
                if photo_url and user.photo_url != photo_url:
                    user.photo_url = photo_url
                    update_fields.append("photo_url")
                if not user.is_active:
                    user.is_active = True
                    update_fields.append("is_active")
                if update_fields:
                    user.save(update_fields=update_fields)

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            status=status.HTTP_200_OK,
        )


class GetMeView(APIView):
    serializer_class = UserSerializer

    @extend_schema(
        summary="Get current user information",
        description="Returns the authenticated user's information.",
        responses={
            200: UserSerializer,
            401: OpenApiResponse(
                description="Unauthorized - Invalid or missing authentication token",
            ),
        },
    )
    def get(self, request):
        if not request.user.is_authenticated:
            return Response(
                {"error": "Authentication required"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = self.serializer_class(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)
