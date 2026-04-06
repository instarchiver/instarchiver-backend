from rest_framework import serializers

from instagram.models.user_follow import UserFollow


class UserFollowSerializer(serializers.ModelSerializer):
    """
    Serializes a UserFollow record from the perspective of the "other" user.
    Pass context['relationship'] = 'followers' to expose the follower user,
    or 'following' (default) to expose the following user.
    """

    uuid = serializers.SerializerMethodField()
    instagram_id = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()
    is_private = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()
    is_mutual = serializers.BooleanField(read_only=True)

    class Meta:
        model = UserFollow
        fields = [
            "uuid",
            "instagram_id",
            "username",
            "full_name",
            "profile_picture",
            "is_private",
            "is_verified",
            "is_mutual",
            "first_seen_at",
        ]

    def _get_related_user(self, obj):
        if self.context.get("relationship") == "followers":
            return obj.follower
        return obj.following

    def get_uuid(self, obj):
        return str(self._get_related_user(obj).uuid)

    def get_instagram_id(self, obj):
        return self._get_related_user(obj).instagram_id

    def get_username(self, obj):
        return self._get_related_user(obj).username

    def get_full_name(self, obj):
        return self._get_related_user(obj).full_name

    def get_profile_picture(self, obj):
        user = self._get_related_user(obj)
        if not user.profile_picture:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(user.profile_picture.url)
        return user.profile_picture.url

    def get_is_private(self, obj):
        return self._get_related_user(obj).is_private

    def get_is_verified(self, obj):
        return self._get_related_user(obj).is_verified
