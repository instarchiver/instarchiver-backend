from rest_framework import serializers

from instagram.models import Story
from instagram.serializers.users import InstagramUserDetailSerializer
from instagram.serializers.users import InstagramUserListSerializer


class StoryListSerializer(serializers.ModelSerializer):
    user = InstagramUserListSerializer(read_only=True)

    class Meta:
        model = Story
        fields = [
            "story_id",
            "user",
            "thumbnail",
            "blur_data_url",
            "media",
            "is_flagged",
            "created_at",
            "story_created_at",
        ]


class StoryDetailSerializer(serializers.ModelSerializer):
    user = InstagramUserDetailSerializer(read_only=True)

    class Meta:
        model = Story
        fields = [
            "story_id",
            "user",
            "thumbnail",
            "blur_data_url",
            "media",
            "is_flagged",
            "created_at",
            "story_created_at",
        ]
