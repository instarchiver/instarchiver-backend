from rest_framework import serializers

from instagram.models import Post
from instagram.models import PostMedia
from instagram.serializers.users import InstagramUserDetailSerializer
from instagram.serializers.users import InstagramUserListSerializer


class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = [
            "id",
            "thumbnail_url",
            "blur_data_url",
            "media_url",
            "thumbnail",
            "media",
            "width",
            "height",
            "created_at",
            "updated_at",
        ]


class PostListSerializer(serializers.ModelSerializer):
    user = InstagramUserListSerializer(read_only=True)
    media_count = serializers.SerializerMethodField()
    media = PostMediaSerializer(source="postmedia_set", many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            "id",
            "variant",
            "thumbnail_url",
            "thumbnail",
            "blur_data_url",
            "width",
            "height",
            "caption",
            "thumbnail_insight",
            "media_count",
            "is_flagged",
            "post_created_at",
            "created_at",
            "updated_at",
            "media",
            "user",
        ]

    def get_media_count(self, obj):
        """Return the count of media items for this post."""
        return obj.media_count


class PostDetailSerializer(serializers.ModelSerializer):
    user = InstagramUserDetailSerializer(read_only=True)
    media = PostMediaSerializer(source="postmedia_set", many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            "id",
            "variant",
            "thumbnail_url",
            "thumbnail",
            "blur_data_url",
            "caption",
            "width",
            "height",
            "is_flagged",
            "post_created_at",
            "created_at",
            "updated_at",
            "media",
            "user",
        ]
