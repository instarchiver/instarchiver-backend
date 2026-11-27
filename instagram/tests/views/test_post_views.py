from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.db import transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from pgvector.django import L2Distance
from rest_framework import status
from rest_framework.test import APIClient

from instagram.models import Post
from instagram.tests.factories import InstagramUserFactory
from instagram.tests.factories import PostFactory
from instagram.tests.factories import PostMediaFactory


class PostListViewTest(TestCase):
    """Test suite for PostListView endpoint."""

    def setUp(self):
        """Set up test client and common test data."""
        cache.clear()
        self.client = APIClient()
        self.url = reverse("instagram:post_list")

    def test_list_posts_success(self):
        """Test successful retrieval of posts list."""
        expected_count = 5
        PostFactory.create_batch(expected_count)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == expected_count

    def test_list_posts_unauthenticated_allowed(self):
        """Test unauthenticated access (IsAuthenticatedOrReadOnly)."""
        PostFactory.create_batch(3)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK

    def test_list_posts_pagination(self):
        """Test that pagination works correctly with cursor pagination."""
        # Create posts to test pagination
        total_posts = 15
        PostFactory.create_batch(total_posts)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert "next" in response.data
        assert "previous" in response.data
        assert len(response.data["results"]) == total_posts

    def test_list_posts_with_page_size_param(self):
        """Test custom page size parameter."""
        custom_page_size = 5
        PostFactory.create_batch(10)

        response = self.client.get(self.url, {"page_size": custom_page_size})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == custom_page_size

    def test_list_posts_max_page_size(self):
        """Test that max page size is enforced (100)."""
        max_page_size = 100
        PostFactory.create_batch(50)

        response = self.client.get(self.url, {"page_size": 200})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) <= max_page_size

    def test_list_posts_ordering_default(self):
        """Test default ordering by created_at descending."""
        PostFactory.create_batch(5)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Most recent post should be first
        created_at_values = [post["created_at"] for post in results]
        assert created_at_values == sorted(created_at_values, reverse=True)

    def test_response_structure(self):
        """Test that the response contains expected fields."""
        PostFactory()

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_post = results[0]
        expected_fields = [
            "id",
            "variant",
            "thumbnail_url",
            "thumbnail",
            "blur_data_url",
            "media_count",
            "is_flagged",
            "created_at",
            "updated_at",
            "user",
        ]

        for field in expected_fields:
            assert field in first_post, f"Field '{field}' missing from response"

    def test_is_flagged_false_by_default(self):
        """Test that is_flagged defaults to False for new posts."""
        PostFactory(is_flagged=False)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        first_post = response.data["results"][0]
        assert first_post["is_flagged"] is False

    def test_is_flagged_true_for_flagged_post(self):
        """Test that is_flagged is True for flagged posts."""
        PostFactory(is_flagged=True)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        first_post = response.data["results"][0]
        assert first_post["is_flagged"] is True

    def test_nested_user_structure(self):
        """Test that nested user object contains expected fields."""
        user = InstagramUserFactory(username="testuser")
        PostFactory(user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_post = results[0]
        user_data = first_post["user"]

        expected_user_fields = [
            "uuid",
            "instagram_id",
            "username",
            "full_name",
            "profile_picture",
            "biography",
            "is_private",
            "is_verified",
            "media_count",
            "follower_count",
            "following_count",
            "allow_auto_update_stories",
            "allow_auto_update_profile",
            "created_at",
            "updated_at",
            "api_updated_at",
            "has_stories",
            "has_history",
        ]

        for field in expected_user_fields:
            assert field in user_data, f"Field '{field}' missing from user data"

    def test_user_has_stories_annotation(self):
        """Test that user's has_stories annotation is correct."""
        user = InstagramUserFactory(username="postuser")
        PostFactory(user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_post = results[0]
        # User has no stories, so has_stories should be False
        assert first_post["user"]["has_stories"] is False

    def test_user_has_history_annotation(self):
        """Test that user's has_history annotation is correct."""
        user = InstagramUserFactory(username="historyuser", full_name="Original Name")
        user.full_name = "Updated Name"
        user.save()

        PostFactory(user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_post = results[0]
        assert first_post["user"]["has_history"] is True

    def test_empty_list(self):
        """Test response when no posts exist."""
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 0

    def test_cursor_pagination_next_page(self):
        """Test navigating to the next page using cursor pagination."""
        page_size = 10
        PostFactory.create_batch(15)

        # Get first page
        response = self.client.get(self.url, {"page_size": page_size})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == page_size
        assert response.data["next"] is not None

        # Extract cursor from next URL
        next_url = response.data["next"]
        cursor_start = next_url.find("cursor=") + 7
        cursor_end = next_url.find("&", cursor_start)
        if cursor_end == -1:
            cursor = next_url[cursor_start:]
        else:
            cursor = next_url[cursor_start:cursor_end]

        # Get second page
        response = self.client.get(
            self.url,
            {"page_size": page_size, "cursor": cursor},
        )
        assert response.status_code == status.HTTP_200_OK
        # Second page should have remaining 5 posts (15 total - 10 from first page)
        assert len(response.data["results"]) == 5  # noqa: PLR2004

    def test_posts_from_multiple_users(self):
        """Test that posts from multiple users are returned correctly."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")

        PostFactory.create_batch(3, user=user1)
        PostFactory.create_batch(2, user=user2)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 5  # noqa: PLR2004

        # Verify we have posts from both users
        usernames = {post["user"]["username"] for post in results}
        assert "user1" in usernames
        assert "user2" in usernames

    def test_post_with_same_user_multiple_times(self):
        """Test that the same user appears correctly in multiple posts."""
        user = InstagramUserFactory(username="multiuser")
        PostFactory.create_batch(3, user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3  # noqa: PLR2004

        # All posts should have the same user
        for post in results:
            assert post["user"]["username"] == "multiuser"
            assert post["user"]["uuid"] == str(user.uuid)

    def test_search_by_username(self):
        """Test searching posts by user's username."""
        user1 = InstagramUserFactory(username="johndoe")
        user2 = InstagramUserFactory(username="janedoe")
        user3 = InstagramUserFactory(username="alice")

        PostFactory.create_batch(2, user=user1)
        PostFactory.create_batch(2, user=user2)
        PostFactory.create_batch(1, user=user3)

        response = self.client.get(self.url, {"search": "doe"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 4  # noqa: PLR2004

        # All results should be from users with "doe" in username
        usernames = {post["user"]["username"] for post in results}
        assert usernames == {"johndoe", "janedoe"}

    def test_search_by_full_name(self):
        """Test searching posts by user's full name."""
        user1 = InstagramUserFactory(username="user1", full_name="John Smith")
        user2 = InstagramUserFactory(username="user2", full_name="Jane Smith")
        user3 = InstagramUserFactory(username="user3", full_name="Bob Johnson")

        PostFactory.create_batch(2, user=user1)
        PostFactory.create_batch(2, user=user2)
        PostFactory.create_batch(1, user=user3)

        response = self.client.get(self.url, {"search": "Smith"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 4  # noqa: PLR2004

        # All results should be from users with "Smith" in full_name
        full_names = {post["user"]["full_name"] for post in results}
        assert full_names == {"John Smith", "Jane Smith"}

    def test_search_by_biography(self):
        """Test searching posts by user's biography."""
        user1 = InstagramUserFactory(
            username="user1",
            biography="I love photography and travel",
        )
        user2 = InstagramUserFactory(
            username="user2",
            biography="Photography enthusiast",
        )
        user3 = InstagramUserFactory(username="user3", biography="Food blogger")

        PostFactory.create_batch(2, user=user1)
        PostFactory.create_batch(2, user=user2)
        PostFactory.create_batch(1, user=user3)

        response = self.client.get(self.url, {"search": "photography"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 4  # noqa: PLR2004

        # All results should be from users with "photography" in biography
        usernames = {post["user"]["username"] for post in results}
        assert usernames == {"user1", "user2"}

    def test_search_by_caption(self):
        """Test searching posts by caption content."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")
        user3 = InstagramUserFactory(username="user3")

        PostFactory.create_batch(
            2,
            user=user1,
            caption="Beautiful sunset at the beach #sunset #nature",
        )
        PostFactory.create_batch(
            2,
            user=user2,
            caption="Amazing sunset view from the mountains",
        )
        PostFactory.create_batch(1, user=user3, caption="City lights at night")

        response = self.client.get(self.url, {"search": "sunset"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 4  # noqa: PLR2004

        # All results should have "sunset" in caption
        for post in results:
            assert "sunset" in post["caption"].lower()

    def test_search_case_insensitive(self):
        """Test that search is case-insensitive."""
        user = InstagramUserFactory(username="TestUser", full_name="Test User")
        PostFactory.create_batch(2, user=user)

        # Test with lowercase
        response = self.client.get(self.url, {"search": "testuser"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2  # noqa: PLR2004

        # Test with uppercase
        response = self.client.get(self.url, {"search": "TESTUSER"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2  # noqa: PLR2004

    def test_search_no_results(self):
        """Test search with no matching results."""
        user = InstagramUserFactory(username="testuser")
        PostFactory.create_batch(2, user=user)

        response = self.client.get(self.url, {"search": "nonexistent"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_search_partial_match(self):
        """Test that search works with partial matches."""
        user = InstagramUserFactory(username="photography_lover")
        PostFactory.create_batch(2, user=user)

        response = self.client.get(self.url, {"search": "photo"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2  # noqa: PLR2004

    def test_filter_by_user(self):
        """Test filtering posts by specific user."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")

        PostFactory.create_batch(3, user=user1)
        PostFactory.create_batch(2, user=user2)

        response = self.client.get(self.url, {"user": str(user1.uuid)})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3  # noqa: PLR2004

        # All results should be from user1
        for post in results:
            assert post["user"]["uuid"] == str(user1.uuid)
            assert post["user"]["username"] == "user1"

    def test_filter_by_user_no_posts(self):
        """Test filtering by user who has no posts."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")

        PostFactory.create_batch(3, user=user1)

        response = self.client.get(self.url, {"user": str(user2.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_filter_by_invalid_user_uuid(self):
        """Test filtering with invalid user UUID."""
        PostFactory.create_batch(2)

        response = self.client.get(self.url, {"user": "invalid-uuid"})

        # Should return 400 or empty results depending on DjangoFilterBackend config
        # Typically returns empty results for invalid UUID
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]

    def test_filter_by_variant_normal(self):
        """Test filtering posts by variant (normal)."""
        user = InstagramUserFactory(username="testuser")
        PostFactory.create_batch(3, user=user, variant=Post.POST_VARIANT_NORMAL)
        PostFactory.create_batch(2, user=user, variant=Post.POST_VARIANT_CAROUSEL)

        response = self.client.get(self.url, {"variant": Post.POST_VARIANT_NORMAL})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3  # noqa: PLR2004

        # All results should have normal variant
        for post in results:
            assert post["variant"] == Post.POST_VARIANT_NORMAL

    def test_filter_by_variant_carousel(self):
        """Test filtering posts by variant (carousel)."""
        user = InstagramUserFactory(username="testuser")
        PostFactory.create_batch(3, user=user, variant=Post.POST_VARIANT_NORMAL)
        PostFactory.create_batch(2, user=user, variant=Post.POST_VARIANT_CAROUSEL)

        response = self.client.get(self.url, {"variant": Post.POST_VARIANT_CAROUSEL})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2  # noqa: PLR2004

        # All results should have carousel variant
        for post in results:
            assert post["variant"] == Post.POST_VARIANT_CAROUSEL

    def test_combined_search_and_filter(self):
        """Test using search and filter together."""
        user1 = InstagramUserFactory(username="johndoe", full_name="John Doe")
        user2 = InstagramUserFactory(username="janedoe", full_name="Jane Doe")
        user3 = InstagramUserFactory(username="bobsmith", full_name="Bob Smith")

        PostFactory.create_batch(2, user=user1)
        PostFactory.create_batch(2, user=user2)
        PostFactory.create_batch(1, user=user3)

        # Search for "doe" and filter by user1
        response = self.client.get(
            self.url,
            {"search": "doe", "user": str(user1.uuid)},
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2  # noqa: PLR2004

        # All results should be from user1 and match "doe"
        for post in results:
            assert post["user"]["uuid"] == str(user1.uuid)
            assert "doe" in post["user"]["username"].lower()

    def test_search_with_pagination(self):
        """Test search functionality works with pagination."""
        user = InstagramUserFactory(username="searchuser")
        PostFactory.create_batch(15, user=user)

        response = self.client.get(self.url, {"search": "searchuser", "page_size": 10})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10  # noqa: PLR2004
        assert response.data["next"] is not None

    def test_filter_with_pagination(self):
        """Test filter functionality works with pagination."""
        user = InstagramUserFactory(username="filteruser")
        PostFactory.create_batch(15, user=user)

        response = self.client.get(
            self.url,
            {"user": str(user.uuid), "page_size": 10},
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10  # noqa: PLR2004
        assert response.data["next"] is not None

    def test_media_count_annotation(self):
        """Test that media_count annotation is correct."""
        user = InstagramUserFactory(username="mediauser")
        post = PostFactory(user=user)
        PostMediaFactory.create_batch(3, post=post)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_post = results[0]
        assert first_post["media_count"] == 3  # noqa: PLR2004

    def test_media_count_zero(self):
        """Test that media_count is 0 for posts without media."""
        user = InstagramUserFactory(username="nomediauser")
        PostFactory(user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_post = results[0]
        assert first_post["media_count"] == 0

    def test_ordering_by_created_at_asc(self):
        """Test ordering posts by created_at ascending."""
        PostFactory.create_batch(5)

        response = self.client.get(self.url, {"ordering": "created_at"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Oldest post should be first
        created_at_values = [post["created_at"] for post in results]
        assert created_at_values == sorted(created_at_values)

    def test_ordering_by_updated_at_desc(self):
        """Test ordering posts by updated_at descending."""
        PostFactory.create_batch(5)

        response = self.client.get(self.url, {"ordering": "-updated_at"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Most recently updated post should be first
        updated_at_values = [post["updated_at"] for post in results]
        assert updated_at_values == sorted(updated_at_values, reverse=True)


class PostDetailViewTest(TestCase):
    """Test suite for PostDetailView endpoint."""

    def setUp(self):
        """Set up test client and common test data."""
        cache.clear()
        self.client = APIClient()

    def test_retrieve_post_success(self):
        """Test successful retrieval of a single post."""
        user = InstagramUserFactory(username="testuser")
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == post.id

    def test_retrieve_post_not_found(self):
        """Test retrieving a non-existent post returns 404."""
        url = reverse(
            "instagram:post_detail",
            kwargs={"id": "9999999999999999999"},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_post_unauthenticated_allowed(self):
        """Test unauthenticated access (IsAuthenticatedOrReadOnly)."""
        post = PostFactory()

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

    def test_response_structure(self):
        """Test that the response contains expected fields."""
        post = PostFactory()

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

        expected_fields = [
            "id",
            "variant",
            "thumbnail_url",
            "thumbnail",
            "blur_data_url",
            "media",
            "is_flagged",
            "created_at",
            "updated_at",
            "user",
        ]

        for field in expected_fields:
            assert field in response.data, f"Field '{field}' missing from response"

    def test_is_flagged_false_by_default(self):
        """Test that is_flagged defaults to False for new posts."""
        post = PostFactory(is_flagged=False)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_flagged"] is False

    def test_is_flagged_true_for_flagged_post(self):
        """Test that is_flagged is True for flagged posts."""
        post = PostFactory(is_flagged=True)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["is_flagged"] is True

    def test_nested_user_detail_structure(self):
        """Test that nested user object contains detailed fields."""
        user = InstagramUserFactory(username="detailuser")
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        user_data = response.data["user"]

        expected_user_fields = [
            "uuid",
            "instagram_id",
            "username",
            "full_name",
            "profile_picture",
            "biography",
            "is_private",
            "is_verified",
            "media_count",
            "follower_count",
            "following_count",
            "allow_auto_update_stories",
            "allow_auto_update_profile",
            "auto_update_stories_limit_count",
            "auto_update_profile_limit_count",
            "created_at",
            "updated_at",
            "updated_at_from_api",
            "has_stories",
            "has_history",
        ]

        for field in expected_user_fields:
            assert field in user_data, f"Field '{field}' missing from user data"

    def test_user_has_stories_annotation(self):
        """Test that user's has_stories annotation is correct."""
        user = InstagramUserFactory(username="postuser")
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # User has no stories, so has_stories should be False
        assert response.data["user"]["has_stories"] is False

    def test_user_has_history_annotation(self):
        """Test that user's has_history annotation is correct."""
        user = InstagramUserFactory(username="historyuser", full_name="Original Name")
        user.full_name = "Updated Name"
        user.save()

        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["has_history"] is True

    def test_user_without_history(self):
        """Test that newly created user has has_history as True.

        django-simple-history creates initial record on creation.
        """
        user = InstagramUserFactory(username="nohistoryuser")
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # has_history is True because django-simple-history creates a record on creation
        assert response.data["user"]["has_history"] is True

    def test_post_id_field_matches(self):
        """Test that post id in response matches the requested post."""
        post = PostFactory()

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == post.id

    def test_user_uuid_field_matches(self):
        """Test that user UUID in response matches the post's user."""
        user = InstagramUserFactory()
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["uuid"] == str(user.uuid)

    def test_media_list_structure(self):
        """Test that media list contains expected fields."""
        user = InstagramUserFactory(username="mediauser")
        post = PostFactory(user=user)
        PostMediaFactory.create_batch(3, post=post)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        media_list = response.data["media"]
        assert len(media_list) == 3  # noqa: PLR2004

        expected_media_fields = [
            "id",
            "thumbnail_url",
            "media_url",
            "thumbnail",
            "media",
            "created_at",
            "updated_at",
        ]

        for media in media_list:
            for field in expected_media_fields:
                assert field in media, f"Field '{field}' missing from media data"

    def test_media_list_empty(self):
        """Test that media list is empty for posts without media."""
        user = InstagramUserFactory(username="nomediauser")
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        media_list = response.data["media"]
        assert len(media_list) == 0

    def test_post_variant_normal(self):
        """Test retrieving a post with normal variant."""
        user = InstagramUserFactory(username="normaluser")
        post = PostFactory(user=user, variant=Post.POST_VARIANT_NORMAL)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["variant"] == Post.POST_VARIANT_NORMAL

    def test_post_variant_carousel(self):
        """Test retrieving a post with carousel variant."""
        user = InstagramUserFactory(username="carouseluser")
        post = PostFactory(user=user, variant=Post.POST_VARIANT_CAROUSEL)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["variant"] == Post.POST_VARIANT_CAROUSEL

    def test_post_with_multiple_media(self):
        """Test retrieving a carousel post with multiple media items."""
        user = InstagramUserFactory(username="carouseluser")
        post = PostFactory(user=user, variant=Post.POST_VARIANT_CAROUSEL)
        media_items = PostMediaFactory.create_batch(5, post=post)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["variant"] == Post.POST_VARIANT_CAROUSEL
        assert len(response.data["media"]) == 5  # noqa: PLR2004

        # Verify all media items are returned
        returned_media_ids = {media["id"] for media in response.data["media"]}
        expected_media_ids = {media.id for media in media_items}
        assert returned_media_ids == expected_media_ids

    def test_cache_hit_on_second_request(self):
        """Test that second request to same post uses cache."""

        # Clear cache before test
        cache.clear()

        user = InstagramUserFactory(username="cacheuser")
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})

        # First request - should cache the response
        response1 = self.client.get(url)
        assert response1.status_code == status.HTTP_200_OK

        # Verify cache key exists
        cache_key = f"post_detail_{post.id}"
        cached_data = cache.get(cache_key)
        assert cached_data is not None

        # Second request - should use cache
        response2 = self.client.get(url)
        assert response2.status_code == status.HTTP_200_OK

        # Both responses should be identical
        assert response1.data == response2.data

    def test_cache_miss_on_first_request(self):
        """Test that first request doesn't find cache and creates it."""

        # Clear cache before test
        cache.clear()

        user = InstagramUserFactory(username="cachemissuser")
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})

        # Verify cache doesn't exist before request
        cache_key = f"post_detail_{post.id}"
        assert cache.get(cache_key) is None

        # Make request
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        # Verify cache now exists
        cached_data = cache.get(cache_key)
        assert cached_data is not None
        assert cached_data["id"] == post.id

    def test_cache_expires_after_ttl(self):
        """Test that cache expires after 30 seconds."""

        # Clear cache before test
        cache.clear()

        user = InstagramUserFactory(username="cachettluser")
        post = PostFactory(user=user)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        cache_key = f"post_detail_{post.id}"

        # First request - creates cache
        response1 = self.client.get(url)
        assert response1.status_code == status.HTTP_200_OK

        # Verify cache exists
        assert cache.get(cache_key) is not None

        # Manually delete cache to simulate expiration
        cache.delete(cache_key)

        # Verify cache is gone
        assert cache.get(cache_key) is None

        # Second request should create new cache
        response2 = self.client.get(url)
        assert response2.status_code == status.HTTP_200_OK

        # Cache should exist again
        assert cache.get(cache_key) is not None

    def test_different_posts_have_different_cache_keys(self):
        """Test that different posts use different cache keys."""

        # Clear cache before test
        cache.clear()

        user = InstagramUserFactory(username="multipostuser")
        post1 = PostFactory(user=user)
        post2 = PostFactory(user=user)

        url1 = reverse("instagram:post_detail", kwargs={"id": post1.id})
        url2 = reverse("instagram:post_detail", kwargs={"id": post2.id})

        # Request both posts
        response1 = self.client.get(url1)
        response2 = self.client.get(url2)

        assert response1.status_code == status.HTTP_200_OK
        assert response2.status_code == status.HTTP_200_OK

        # Verify both have separate cache keys
        cache_key1 = f"post_detail_{post1.id}"
        cache_key2 = f"post_detail_{post2.id}"

        cached1 = cache.get(cache_key1)
        cached2 = cache.get(cache_key2)

        assert cached1 is not None
        assert cached2 is not None
        assert cached1["id"] == post1.id
        assert cached2["id"] == post2.id
        assert cached1["id"] != cached2["id"]

    def test_cache_contains_correct_data(self):
        """Test that cached data matches the actual response."""

        # Clear cache before test
        cache.clear()

        user = InstagramUserFactory(username="cachedatauser")
        post = PostFactory(user=user, caption="Test caption for caching")
        PostMediaFactory.create_batch(2, post=post)

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        cache_key = f"post_detail_{post.id}"

        # Make request to populate cache
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK

        # Get cached data
        cached_data = cache.get(cache_key)

        # Verify cached data matches response
        assert cached_data["id"] == post.id
        assert cached_data["caption"] == "Test caption for caching"
        assert cached_data["user"]["username"] == "cachedatauser"
        assert len(cached_data["media"]) == 2  # noqa: PLR2004

    def test_view_count_not_in_response(self):
        """Test that view_count is never exposed via the API."""
        post = PostFactory()

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "view_count" not in response.data

    @patch("instagram.views.posts.increment_post_view_count.delay")
    def test_first_view_triggers_increment_task(self, mock_delay):
        post = PostFactory()

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        self.client.get(url)

        mock_delay.assert_called_once_with(post.id)

    @patch("instagram.views.posts.increment_post_view_count.delay")
    def test_repeat_view_same_ip_does_not_trigger_again(self, mock_delay):
        post = PostFactory()

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        self.client.get(url)
        self.client.get(url)

        mock_delay.assert_called_once_with(post.id)

    @patch("instagram.views.posts.increment_post_view_count.delay")
    def test_view_from_different_ip_triggers_again_on_cache_hit(self, mock_delay):
        """Even though the second request is served from the 30s response
        cache, view tracking must still fire for a new IP."""
        post = PostFactory()

        url = reverse("instagram:post_detail", kwargs={"id": post.id})
        self.client.get(url, REMOTE_ADDR="1.1.1.1")
        self.client.get(url, REMOTE_ADDR="2.2.2.2")

        expected_call_count = 2
        assert mock_delay.call_count == expected_call_count

    @patch("instagram.views.posts.increment_post_view_count.delay")
    def test_404_does_not_trigger_increment(self, mock_delay):
        url = reverse(
            "instagram:post_detail",
            kwargs={"id": "9999999999999999999"},
        )

        response = self.client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_delay.assert_not_called()


class PostSimilarViewTest(TestCase):
    """Test suite for PostSimilarView endpoint."""

    def setUp(self):
        """Set up test client and common test data."""
        self.client = APIClient()

    def test_similar_posts_success(self):
        """Test successful retrieval of similar posts ordered by similarity."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create similar posts with embeddings
        PostFactory(
            user=user,
            embedding=[0.1, 0.2, 0.3] * 512,  # Very similar
        )
        PostFactory(
            user=user,
            embedding=[0.5, 0.6, 0.7] * 512,  # Less similar
        )

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 2  # noqa: PLR2004

    def test_similar_posts_pagination(self):
        """Test page number pagination works correctly."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create 25 similar posts with embeddings
        for _ in range(25):
            PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert "count" not in response.data
        assert "next" in response.data
        assert "previous" in response.data
        assert "page=2" in response.data["next"]
        assert len(response.data["results"]) == 20  # noqa: PLR2004 (default page size)

    def test_similar_posts_custom_page_size(self):
        """Test custom page_size parameter."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create 15 similar posts with embeddings
        for _ in range(15):
            PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url, {"page_size": 5})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 5  # noqa: PLR2004

    def test_similar_posts_max_page_size(self):
        """Test that max page size is enforced (100)."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create 50 similar posts with embeddings
        for _ in range(50):
            PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url, {"page_size": 200})

        assert response.status_code == status.HTTP_200_OK
        # Should be limited to max_page_size of 100
        assert len(response.data["results"]) <= 100  # noqa: PLR2004

    def test_similar_posts_excludes_source_post(self):
        """Test that source post is not included in results."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create similar posts with embeddings
        for _ in range(5):
            PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Verify source post is not in results
        result_ids = [post["id"] for post in results]
        assert source_post.id not in result_ids

    def test_similar_posts_only_with_embeddings(self):
        """Test that only posts with embeddings are returned."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create posts with embeddings
        PostFactory.create_batch(3, user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create posts without embeddings
        PostFactory.create_batch(2, user=user, embedding=None)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3  # noqa: PLR2004

        # Verify all results have embeddings (not null)
        for post in results:
            # The embedding field is not exposed in serializer, but we know
            # only posts with embeddings should be returned
            assert post["id"] is not None

    def test_similar_posts_post_not_found(self):
        """Test handling of non-existent post ID."""
        url = reverse(
            "instagram:post_similar",
            kwargs={"id": "9999999999999999999"},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Should return empty results for non-existent post
        assert len(response.data["results"]) == 0

    def test_similar_posts_no_embedding(self):
        """Test handling of source post without embedding."""
        user = InstagramUserFactory(username="testuser")

        # Create source post WITHOUT embedding
        source_post = PostFactory(user=user, embedding=None)

        # Create posts with embeddings
        PostFactory.create_batch(3, user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Should return empty results when source post has no embedding
        assert len(response.data["results"]) == 0

    def test_similar_posts_no_other_posts_with_embeddings(self):
        """Test when no other posts have embeddings."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create posts without embeddings
        PostFactory.create_batch(3, user=user, embedding=None)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Should return empty results when no other posts have embeddings
        assert len(response.data["results"]) == 0

    def test_similar_posts_response_structure(self):
        """Test that response contains expected pagination structure."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create similar posts
        PostFactory.create_batch(5, user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

        # Check non-counting pagination structure
        assert "count" not in response.data
        assert "next" in response.data
        assert "previous" in response.data
        assert "results" in response.data

        # Check post structure
        results = response.data["results"]
        assert len(results) > 0

        first_post = results[0]
        expected_fields = [
            "id",
            "variant",
            "thumbnail_url",
            "thumbnail",
            "blur_data_url",
            "media_count",
            "is_flagged",
            "created_at",
            "updated_at",
            "user",
        ]

        for field in expected_fields:
            assert field in first_post, f"Field '{field}' missing from response"

    def test_similar_posts_unauthenticated_allowed(self):
        """Test unauthenticated access (IsAuthenticatedOrReadOnly)."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create similar posts
        PostFactory.create_batch(3, user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

    def test_similar_posts_page_navigation(self):
        """Test navigating between pages."""
        user = InstagramUserFactory(username="testuser")

        # Create source post with embedding
        source_post = PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create 25 similar posts
        for _ in range(25):
            PostFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})

        # Get first page
        response = self.client.get(url, {"page_size": 10})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10  # noqa: PLR2004
        assert response.data["next"] is not None

        # Get second page
        response = self.client.get(url, {"page_size": 10, "page": 2})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10  # noqa: PLR2004

        # Get third page
        response = self.client.get(url, {"page_size": 10, "page": 3})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 5  # noqa: PLR2004 (remaining posts)

    def test_similar_posts_from_multiple_users(self):
        """Test that similar posts from different users are returned."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")

        # Create source post with embedding
        source_post = PostFactory(user=user1, embedding=[0.1, 0.2, 0.3] * 512)

        # Create similar posts from different users
        PostFactory.create_batch(2, user=user1, embedding=[0.1, 0.2, 0.3] * 512)
        PostFactory.create_batch(2, user=user2, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 4  # noqa: PLR2004

        # Verify we have posts from both users
        usernames = {post["user"]["username"] for post in results}
        assert "user1" in usernames
        assert "user2" in usernames

    def test_similar_posts_no_count_query_and_direct_l2_order(self):
        """PostSimilarView runs no COUNT(*) and orders directly by <-> operator."""
        user = InstagramUserFactory(username="testuser")
        source_post = PostFactory(
            user=user,
            embedding=[0.1] * 1536,
            raw_data={"a": 1},
        )
        PostFactory(user=user, embedding=[0.2] * 1536, raw_data={"b": 2})

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        sqls = [q["sql"] for q in ctx.captured_queries]
        assert not any("COUNT(*)" in sql.upper() for sql in sqls)

        rank_queries = [sql for sql in sqls if "<->" in sql]
        assert len(rank_queries) == 1
        rank_sql = rank_queries[0]
        assert "1 -" not in rank_sql
        assert "DESC" not in rank_sql.upper().split("ORDER BY", 1)[1]
        select_part = rank_sql.split(" FROM ", 1)[0]
        assert '"raw_data"' not in select_part
        assert '"embedding"' not in select_part

        lookup_queries = [
            sql for sql in sqls if 'FROM "instagram_post"' in sql and "<->" not in sql
        ]
        assert len(lookup_queries) == 1
        assert '"raw_data"' not in lookup_queries[0].split(" FROM ", 1)[0]

    def test_similar_posts_ordering_by_distance(self):
        """Posts with closer embeddings appear before farther posts."""
        user = InstagramUserFactory(username="testuser")
        source_post = PostFactory(user=user, embedding=[0.0] * 1536)
        far_post = PostFactory(user=user, embedding=[1.0] * 1536)
        near_post = PostFactory(user=user, embedding=[0.05] * 1536)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in response.data["results"]]
        assert ids == [near_post.id, far_post.id]

    def test_similar_posts_pagination_edge_cases(self):
        """Invalid, out-of-range, and capped pages return 404 or proper links."""
        user = InstagramUserFactory(username="testuser")
        source_post = PostFactory(user=user, embedding=[0.1] * 1536)
        for _ in range(25):
            PostFactory(user=user, embedding=[0.2] * 1536)

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        for bad_page in ("0", "-1", "abc", "last", "3", "11"):
            resp = self.client.get(url, {"page": bad_page})
            assert resp.status_code == status.HTTP_404_NOT_FOUND

        page2 = self.client.get(url, {"page": 2, "page_size": 10})
        assert page2.status_code == status.HTTP_200_OK
        assert "page=" not in page2.data["previous"]

        page3 = self.client.get(url, {"page": 3, "page_size": 10})
        assert page3.status_code == status.HTTP_200_OK
        assert "page=2" in page3.data["previous"]

    def test_similar_posts_max_results_cap(self):
        """Pagination caps total reachable results at max_results (200)."""
        user = InstagramUserFactory(username="testuser")
        source_post = PostFactory(user=user, embedding=[0.1] * 1536)
        for i in range(205):
            PostFactory(
                user=user,
                embedding=[float(i + 1) / 1000.0] + [0.0] * 1535,
            )

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        page2 = self.client.get(url, {"page": 2, "page_size": 100})
        assert page2.status_code == status.HTTP_200_OK
        assert len(page2.data["results"]) == 100  # noqa: PLR2004
        assert page2.data["next"] is None

        page3 = self.client.get(url, {"page": 3, "page_size": 100})
        assert page3.status_code == status.HTTP_404_NOT_FOUND

    def test_similar_posts_over_40_distinct_embeddings(self):
        """Paging beyond ef_search=40 returns all distinct posts without duplicates."""
        user = InstagramUserFactory(username="testuser")
        source_post = PostFactory(user=user, embedding=[0.0] * 1536)
        for i in range(1, 61):
            PostFactory(
                user=user,
                embedding=[float(i) / 100.0] + [0.0] * 1535,
            )

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        resp_50 = self.client.get(url, {"page_size": 50})
        assert resp_50.status_code == status.HTTP_200_OK
        assert len(resp_50.data["results"]) == 50  # noqa: PLR2004
        assert resp_50.data["next"] is not None

        seen_ids = []
        for page in (1, 2, 3):
            resp = self.client.get(url, {"page": page, "page_size": 20})
            assert resp.status_code == status.HTTP_200_OK
            seen_ids.extend(item["id"] for item in resp.data["results"])

        assert len(seen_ids) == 60  # noqa: PLR2004
        assert len(set(seen_ids)) == 60  # noqa: PLR2004

    def test_similar_posts_over_40_identical_embeddings(self):
        """Paging through >40 tied embeddings yields deterministic PK order."""
        user = InstagramUserFactory(username="testuser")
        source_post = PostFactory(user=user, embedding=[0.0] * 1536)
        tied_ids = sorted(
            PostFactory(user=user, embedding=[0.1] * 1536).id for _ in range(60)
        )
        for i in range(10):
            PostFactory(
                user=user,
                embedding=[float(i + 5)] + [0.0] * 1535,
            )

        url = reverse("instagram:post_similar", kwargs={"id": source_post.id})
        seen_ids = []
        for page in (1, 2, 3):
            resp = self.client.get(url, {"page": page, "page_size": 20})
            assert resp.status_code == status.HTTP_200_OK
            seen_ids.extend(item["id"] for item in resp.data["results"])

        assert seen_ids == tied_ids

    def test_similar_posts_uses_hnsw_index_explain(self):
        """The similarity queryset can use post_embedding_hnsw_idx."""
        qs = (
            Post.objects.filter(embedding__isnull=False)
            .defer("raw_data", "embedding")
            .exclude(id="missing")
            .order_by(L2Distance("embedding", [0.1] * 1536), "id")[:21]
        )
        sql, params = qs.query.sql_with_params()
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute(f"EXPLAIN {sql}", params)
            plan = "\n".join(row[0] for row in cursor.fetchall())

        assert "post_embedding_hnsw_idx" in plan
