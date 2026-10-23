from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import CreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from instagram.models import Story
from instagram.models import User
from instagram.serializers import ProcessInstagramDataSerializer


class ProcessInstagramDataView(CreateAPIView):
    serializer_class = ProcessInstagramDataSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        username = validated_data["username"]
        story_id = validated_data["story_id"]
        thumbnail_url = validated_data["thumbnail"]
        media_url = validated_data["media"]
        created_datetime = validated_data["created_datetime"]

        user, user_created = User.objects.only(
            "uuid",
            "username",
            "created_at",
            "updated_at",
        ).get_or_create(
            username=username,
            defaults={"username": username},
        )

        _, story_created = Story.objects.only("story_id").get_or_create(
            story_id=story_id,
            defaults={
                "user": user,
                "thumbnail_url": thumbnail_url,
                "media_url": media_url,
                "story_created_at": created_datetime,
            },
        )

        response_data = {
            "message": "Instagram data processed successfully",
            "user_created": user_created,
            "story_created": story_created,
            "username": username,
            "story_id": story_id,
            "thumbnail_url": thumbnail_url,
            "media_url": media_url,
            "processed_at": user.updated_at.isoformat()
            if not user_created
            else user.created_at.isoformat(),
        }

        return Response(response_data, status=status.HTTP_201_CREATED)
