from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tools.instagram import InstagramProfileError
from tools.instagram import fetch_instagram_profile
from tools.schemas import instagram_profile_detail_schema


class InstagramProfileDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @instagram_profile_detail_schema
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
