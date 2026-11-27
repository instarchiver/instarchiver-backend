from rest_framework import serializers

from instagram.models import Post
from instagram.models import PostMedia
from instagram.serializers.users import InstagramUserDetailSerializer
from instagram.serializers.users import InstagramUserListSerializer
from instagram.utils import normalize_instagram_post_url


class PostArchiveSerializer(serializers.Serializer):
    """Serializer for archiving an Instagram post from its URL."""

    url = serializers.URLField(
        max_length=2048,
        help_text="Instagram post, reel, or share URL to archive.",
    )

    def validate_url(self, value: str) -> str:
        """Validate and normalize the Instagram post URL."""
        try:
            canonical_url, _ = normalize_instagram_post_url(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return canonical_url


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
            "media_count",
            "is_flagged",
            "post_created_at",
            "created_at",
            "updated_at",
            "media",
            "user",
        ]

    def get_media_count(self, obj):
        """Return the number of media items, counted from the prefetched rows."""
        return len(obj.postmedia_set.all())


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
