import hashlib
import json

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from instagram.tests.factories import InstagramUserFactory
from instagram.tests.factories import StoryFactory


class StoryListViewTest(TestCase):
    """Test suite for StoryListView endpoint."""

    def setUp(self):
        """Set up test client and common test data."""
        cache.clear()
        self.client = APIClient()
        self.url = reverse("instagram:story_list")

    def test_list_stories_success(self):
        """Test successful retrieval of stories list."""
        expected_count = 5
        StoryFactory.create_batch(expected_count)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == expected_count

    def test_list_stories_unauthenticated_allowed(self):
        """Test unauthenticated access (IsAuthenticatedOrReadOnly)."""
        StoryFactory.create_batch(3)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK

    def test_list_stories_pagination(self):
        """Test that pagination works correctly with cursor pagination."""
        # Create stories to test pagination
        total_stories = 15
        StoryFactory.create_batch(total_stories)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert "next" in response.data
        assert "previous" in response.data
        assert len(response.data["results"]) == total_stories

    def test_list_stories_with_page_size_param(self):
        """Test custom page size parameter."""
        custom_page_size = 5
        StoryFactory.create_batch(10)

        response = self.client.get(self.url, {"page_size": custom_page_size})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == custom_page_size

    def test_list_stories_max_page_size(self):
        """Test that max page size is enforced (100)."""
        max_page_size = 100
        StoryFactory.create_batch(50)

        response = self.client.get(self.url, {"page_size": 200})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) <= max_page_size

    def test_list_stories_ordering_default(self):
        """Test default ordering by created_at descending."""
        StoryFactory.create_batch(5)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Most recent story should be first
        created_at_values = [story["created_at"] for story in results]
        assert created_at_values == sorted(created_at_values, reverse=True)

    def test_response_structure(self):
        """Test that the response contains expected fields."""
        StoryFactory()

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_story = results[0]
        expected_fields = [
            "story_id",
            "user",
            "thumbnail",
            "blur_data_url",
            "media",
            "created_at",
            "story_created_at",
        ]

        for field in expected_fields:
            assert field in first_story, f"Field '{field}' missing from response"

    def test_nested_user_structure(self):
        """Test that nested user object contains expected fields."""
        user = InstagramUserFactory(username="testuser")
        StoryFactory(user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_story = results[0]
        user_data = first_story["user"]

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
        user = InstagramUserFactory(username="storyuser")
        StoryFactory(user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_story = results[0]
        assert first_story["user"]["has_stories"] is True

    def test_user_has_history_annotation(self):
        """Test that user's has_history annotation is correct."""
        user = InstagramUserFactory(username="historyuser", full_name="Original Name")
        user.full_name = "Updated Name"
        user.save()

        StoryFactory(user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) > 0

        first_story = results[0]
        assert first_story["user"]["has_history"] is True

    def test_empty_list(self):
        """Test response when no stories exist."""
        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 0

    def test_cursor_pagination_next_page(self):
        """Test navigating to the next page using cursor pagination."""
        page_size = 10
        StoryFactory.create_batch(15)

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
        # Second page should have remaining 5 stories (15 total - 10 from first page)
        assert len(response.data["results"]) == 5  # noqa: PLR2004

    def test_stories_from_multiple_users(self):
        """Test that stories from multiple users are returned correctly."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")

        StoryFactory.create_batch(3, user=user1)
        StoryFactory.create_batch(2, user=user2)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 5  # noqa: PLR2004

        # Verify we have stories from both users
        usernames = {story["user"]["username"] for story in results}
        assert "user1" in usernames
        assert "user2" in usernames

    def test_story_with_same_user_multiple_times(self):
        """Test that the same user appears correctly in multiple stories."""
        user = InstagramUserFactory(username="multiuser")
        StoryFactory.create_batch(3, user=user)

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3  # noqa: PLR2004

        # All stories should have the same user
        for story in results:
            assert story["user"]["username"] == "multiuser"
            assert story["user"]["uuid"] == str(user.uuid)

    def test_search_by_username(self):
        """Test searching stories by user's username."""
        user1 = InstagramUserFactory(username="johndoe")
        user2 = InstagramUserFactory(username="janedoe")
        user3 = InstagramUserFactory(username="alice")

        StoryFactory.create_batch(2, user=user1)
        StoryFactory.create_batch(2, user=user2)
        StoryFactory.create_batch(1, user=user3)

        response = self.client.get(self.url, {"search": "doe"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 4  # noqa: PLR2004

        # All results should be from users with "doe" in username
        usernames = {story["user"]["username"] for story in results}
        assert usernames == {"johndoe", "janedoe"}

    def test_search_by_full_name(self):
        """Test searching stories by user's full name."""
        user1 = InstagramUserFactory(username="user1", full_name="John Smith")
        user2 = InstagramUserFactory(username="user2", full_name="Jane Smith")
        user3 = InstagramUserFactory(username="user3", full_name="Bob Johnson")

        StoryFactory.create_batch(2, user=user1)
        StoryFactory.create_batch(2, user=user2)
        StoryFactory.create_batch(1, user=user3)

        response = self.client.get(self.url, {"search": "Smith"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 4  # noqa: PLR2004

        # All results should be from users with "Smith" in full_name
        full_names = {story["user"]["full_name"] for story in results}
        assert full_names == {"John Smith", "Jane Smith"}

    def test_search_by_biography(self):
        """Test searching stories by user's biography."""
        user1 = InstagramUserFactory(
            username="user1",
            biography="I love photography and travel",
        )
        user2 = InstagramUserFactory(
            username="user2",
            biography="Photography enthusiast",
        )
        user3 = InstagramUserFactory(username="user3", biography="Food blogger")

        StoryFactory.create_batch(2, user=user1)
        StoryFactory.create_batch(2, user=user2)
        StoryFactory.create_batch(1, user=user3)

        response = self.client.get(self.url, {"search": "photography"})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 4  # noqa: PLR2004

        # All results should be from users with "photography" in biography
        usernames = {story["user"]["username"] for story in results}
        assert usernames == {"user1", "user2"}

    def test_search_case_insensitive(self):
        """Test that search is case-insensitive."""
        user = InstagramUserFactory(username="TestUser", full_name="Test User")
        StoryFactory.create_batch(2, user=user)

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
        StoryFactory.create_batch(2, user=user)

        response = self.client.get(self.url, {"search": "nonexistent"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_search_partial_match(self):
        """Test that search works with partial matches."""
        user = InstagramUserFactory(username="photography_lover")
        StoryFactory.create_batch(2, user=user)

        response = self.client.get(self.url, {"search": "photo"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2  # noqa: PLR2004

    def test_filter_by_user(self):
        """Test filtering stories by specific user."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")

        StoryFactory.create_batch(3, user=user1)
        StoryFactory.create_batch(2, user=user2)

        response = self.client.get(self.url, {"user": str(user1.uuid)})

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3  # noqa: PLR2004

        # All results should be from user1
        for story in results:
            assert story["user"]["uuid"] == str(user1.uuid)
            assert story["user"]["username"] == "user1"

    def test_filter_by_user_no_stories(self):
        """Test filtering by user who has no stories."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")

        StoryFactory.create_batch(3, user=user1)

        response = self.client.get(self.url, {"user": str(user2.uuid)})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_filter_by_invalid_user_uuid(self):
        """Test filtering with invalid user UUID."""
        StoryFactory.create_batch(2)

        response = self.client.get(self.url, {"user": "invalid-uuid"})

        # Should return 400 or empty results depending on DjangoFilterBackend config
        # Typically returns empty results for invalid UUID
        assert response.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]

    def test_combined_search_and_filter(self):
        """Test using search and filter together."""
        user1 = InstagramUserFactory(username="johndoe", full_name="John Doe")
        user2 = InstagramUserFactory(username="janedoe", full_name="Jane Doe")
        user3 = InstagramUserFactory(username="bobsmith", full_name="Bob Smith")

        StoryFactory.create_batch(2, user=user1)
        StoryFactory.create_batch(2, user=user2)
        StoryFactory.create_batch(1, user=user3)

        # Search for "doe" and filter by user1
        response = self.client.get(
            self.url,
            {"search": "doe", "user": str(user1.uuid)},
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2  # noqa: PLR2004

        # All results should be from user1 and match "doe"
        for story in results:
            assert story["user"]["uuid"] == str(user1.uuid)
            assert "doe" in story["user"]["username"].lower()

    def test_search_with_pagination(self):
        """Test search functionality works with pagination."""
        user = InstagramUserFactory(username="searchuser")
        StoryFactory.create_batch(15, user=user)

        response = self.client.get(self.url, {"search": "searchuser", "page_size": 10})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10  # noqa: PLR2004
        assert response.data["next"] is not None

    def test_filter_with_pagination(self):
        """Test filter functionality works with pagination."""
        user = InstagramUserFactory(username="filteruser")
        StoryFactory.create_batch(15, user=user)

        response = self.client.get(
            self.url,
            {"user": str(user.uuid), "page_size": 10},
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10  # noqa: PLR2004
        assert response.data["next"] is not None

    def _make_cache_key(self, params: dict) -> str:
        """Helper to replicate the cache key logic from StoryListView."""
        params_key = json.dumps(sorted(params.items()), sort_keys=True)
        md5_hash = hashlib.md5(params_key.encode(), usedforsecurity=False).hexdigest()
        return "story_list_" + md5_hash

    def test_cache_miss_on_first_request(self):
        """Test that first request doesn't find cache and creates it."""
        cache.clear()
        StoryFactory.create_batch(3)

        cache_key = self._make_cache_key({})
        assert cache.get(cache_key) is None

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK

        cached_data = cache.get(cache_key)
        assert cached_data is not None

    def test_cache_hit_on_second_request(self):
        """Test that second request to same URL uses cache."""
        cache.clear()
        StoryFactory.create_batch(3)

        response1 = self.client.get(self.url)
        assert response1.status_code == status.HTTP_200_OK

        cache_key = self._make_cache_key({})
        assert cache.get(cache_key) is not None

        response2 = self.client.get(self.url)
        assert response2.status_code == status.HTTP_200_OK

        assert response1.data == response2.data

    def test_cache_expires_after_ttl(self):
        """Test that cache is regenerated after manual expiration."""
        cache.clear()
        StoryFactory.create_batch(3)

        cache_key = self._make_cache_key({})

        response1 = self.client.get(self.url)
        assert response1.status_code == status.HTTP_200_OK
        assert cache.get(cache_key) is not None

        cache.delete(cache_key)
        assert cache.get(cache_key) is None

        response2 = self.client.get(self.url)
        assert response2.status_code == status.HTTP_200_OK
        assert cache.get(cache_key) is not None

    def test_different_query_params_have_different_cache_keys(self):
        """Test that different query params produce separate cache entries."""
        cache.clear()
        user1 = InstagramUserFactory(username="cacheuser1")
        user2 = InstagramUserFactory(username="cacheuser2")
        StoryFactory.create_batch(2, user=user1)
        StoryFactory.create_batch(2, user=user2)

        response_all = self.client.get(self.url)
        response_user1 = self.client.get(self.url, {"user": str(user1.uuid)})

        assert response_all.status_code == status.HTTP_200_OK
        assert response_user1.status_code == status.HTTP_200_OK

        cache_key_all = self._make_cache_key({})
        cache_key_user1 = self._make_cache_key({"user": [str(user1.uuid)]})

        assert cache_key_all != cache_key_user1
        assert cache.get(cache_key_all) is not None
        assert cache.get(cache_key_user1) is not None

        # Filtered response should have fewer results than unfiltered
        assert len(response_user1.data["results"]) < len(response_all.data["results"])

    def test_cache_contains_correct_data(self):
        """Test that cached data matches the actual response."""
        cache.clear()
        user = InstagramUserFactory(username="cachedatauser")
        StoryFactory.create_batch(2, user=user)

        cache_key = self._make_cache_key({})

        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK

        cached_data = cache.get(cache_key)
        assert cached_data is not None
        assert cached_data["results"] == list(response.data["results"])


class StoryDetailViewTest(TestCase):
    """Test suite for StoryDetailView endpoint."""

    def setUp(self):
        """Set up test client and common test data."""
        self.client = APIClient()

    def test_retrieve_story_success(self):
        """Test successful retrieval of a single story."""
        user = InstagramUserFactory(username="testuser")
        story = StoryFactory(user=user)

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["story_id"] == story.story_id

    def test_retrieve_story_not_found(self):
        """Test retrieving a non-existent story returns 404."""
        url = reverse(
            "instagram:story_detail",
            kwargs={"story_id": "9999999999999999999"},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_story_unauthenticated_allowed(self):
        """Test unauthenticated access (IsAuthenticatedOrReadOnly)."""
        story = StoryFactory()

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

    def test_response_structure(self):
        """Test that the response contains expected fields."""
        story = StoryFactory()

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

        expected_fields = [
            "story_id",
            "user",
            "thumbnail",
            "blur_data_url",
            "media",
            "created_at",
            "story_created_at",
        ]

        for field in expected_fields:
            assert field in response.data, f"Field '{field}' missing from response"

    def test_nested_user_detail_structure(self):
        """Test that nested user object contains detailed fields."""
        user = InstagramUserFactory(username="detailuser")
        story = StoryFactory(user=user)

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
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
        user = InstagramUserFactory(username="storyuser")
        story = StoryFactory(user=user)

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["has_stories"] is True

    def test_user_has_history_annotation(self):
        """Test that user's has_history annotation is correct."""
        user = InstagramUserFactory(username="historyuser", full_name="Original Name")
        user.full_name = "Updated Name"
        user.save()

        story = StoryFactory(user=user)

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["has_history"] is True

    def test_user_without_history(self):
        """Test that newly created user has has_history as True.

        django-simple-history creates initial record on creation.
        """
        user = InstagramUserFactory(username="nohistoryuser")
        story = StoryFactory(user=user)

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # has_history is True because django-simple-history creates a record on creation
        assert response.data["user"]["has_history"] is True

    def test_story_id_field_matches(self):
        """Test that story_id in response matches the requested story."""
        story = StoryFactory()

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["story_id"] == story.story_id

    def test_user_uuid_field_matches(self):
        """Test that user UUID in response matches the story's user."""
        user = InstagramUserFactory()
        story = StoryFactory(user=user)

        url = reverse("instagram:story_detail", kwargs={"story_id": story.story_id})
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["uuid"] == str(user.uuid)


class StorySimilarViewTest(TestCase):
    """Test suite for StorySimilarView endpoint."""

    def setUp(self):
        """Set up test client and common test data."""
        self.client = APIClient()

    def test_similar_stories_success(self):
        """Test successful retrieval of similar stories ordered by similarity."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(
            user=user,
            embedding=[0.1, 0.2, 0.3] * 512,
        )

        # Create similar stories with embeddings
        StoryFactory(
            user=user,
            embedding=[0.1, 0.2, 0.3] * 512,  # Very similar
        )
        StoryFactory(
            user=user,
            embedding=[0.5, 0.6, 0.7] * 512,  # Less similar
        )

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 2  # noqa: PLR2004

    def test_similar_stories_pagination(self):
        """Test pagination works correctly for similar stories."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(
            user=user,
            embedding=[0.1, 0.2, 0.3] * 512,
        )

        # Create 25 similar stories with embeddings
        for _ in range(25):
            StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 20  # noqa: PLR2004, Default page size
        assert response.data["next"] is not None
        assert "page=2" in response.data["next"]

    def test_similar_stories_custom_page_size(self):
        """Test custom page size parameter for similar stories."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(
            user=user,
            embedding=[0.1, 0.2, 0.3] * 512,
        )

        # Create 15 similar stories with embeddings
        for _ in range(15):
            StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url, {"page_size": 10})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10  # noqa: PLR2004

    def test_similar_stories_max_page_size(self):
        """Test that max page size (100) is enforced."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(
            user=user,
            embedding=[0.1, 0.2, 0.3] * 512,
        )

        # Create 50 similar stories with embeddings
        for _ in range(50):
            StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url, {"page_size": 200})  # Request more than max

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 50  # noqa: PLR2004, Not exceeding available

    def test_similar_stories_excludes_source_story(self):
        """Test that the source story is excluded from results."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(
            user=user,
            embedding=[0.1, 0.2, 0.3] * 512,
        )

        # Create similar stories with embeddings
        StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Verify source story is not in results
        story_ids = [story["story_id"] for story in results]
        assert source_story.story_id not in story_ids

    def test_similar_stories_only_with_embeddings(self):
        """Test that only stories with embeddings are returned."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(
            user=user,
            embedding=[0.1, 0.2, 0.3] * 512,
        )

        # Create stories with embeddings
        story_with_embedding = StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create stories without embeddings
        StoryFactory(user=user, embedding=None)
        StoryFactory(user=user, embedding=None)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Only 1 story with embedding should be returned
        assert len(results) == 1
        assert results[0]["story_id"] == story_with_embedding.story_id

    def test_similar_stories_story_not_found(self):
        """Test error response when source story doesn't exist."""
        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": "9999999999999999999"},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Should return empty results
        assert len(response.data["results"]) == 0

    def test_similar_stories_no_embedding(self):
        """Test response when source story has no embedding."""
        user = InstagramUserFactory()

        # Create source story without embedding
        source_story = StoryFactory(user=user, embedding=None)

        # Create other stories with embeddings
        StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)
        StoryFactory(user=user, embedding=[0.5, 0.6, 0.7] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Should return empty results
        assert len(response.data["results"]) == 0

    def test_similar_stories_no_other_stories_with_embeddings(self):
        """Test response when no other stories have embeddings."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create other stories without embeddings
        StoryFactory(user=user, embedding=None)
        StoryFactory(user=user, embedding=None)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Should return empty results
        assert len(response.data["results"]) == 0

    def test_similar_stories_response_structure(self):
        """Test that response structure matches expected format."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create similar stories
        StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "count" in response.data
        assert "next" in response.data
        assert "previous" in response.data
        assert "results" in response.data

        # Verify story fields
        results = response.data["results"]
        assert len(results) > 0

        first_story = results[0]
        expected_fields = [
            "story_id",
            "user",
            "thumbnail",
            "blur_data_url",
            "media",
            "created_at",
            "story_created_at",
        ]

        for field in expected_fields:
            assert field in first_story, f"Field '{field}' missing from response"

        # Verify user fields
        user_data = first_story["user"]
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

    def test_similar_stories_unauthenticated_allowed(self):
        """Test unauthenticated access (IsAuthenticatedOrReadOnly)."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create similar stories
        StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK

    def test_similar_stories_page_navigation(self):
        """Test page navigation with page number pagination."""
        user = InstagramUserFactory()

        # Create source story with embedding
        source_story = StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        # Create 25 similar stories
        for _ in range(25):
            StoryFactory(user=user, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )

        # Get first page
        response = self.client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 20  # noqa: PLR2004
        assert response.data["next"] is not None
        assert response.data["previous"] is None

        # Get second page
        response = self.client.get(url, {"page": 2})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 5  # noqa: PLR2004, Remaining stories
        assert response.data["next"] is None
        assert response.data["previous"] is not None

    def test_similar_stories_from_multiple_users(self):
        """Test that similar stories from different users are returned."""
        user1 = InstagramUserFactory(username="user1")
        user2 = InstagramUserFactory(username="user2")

        # Create source story with embedding
        source_story = StoryFactory(user=user1, embedding=[0.1, 0.2, 0.3] * 512)

        # Create similar stories from different users
        StoryFactory(user=user1, embedding=[0.1, 0.2, 0.3] * 512)
        StoryFactory(user=user2, embedding=[0.1, 0.2, 0.3] * 512)

        url = reverse(
            "instagram:story_similar",
            kwargs={"story_id": source_story.story_id},
        )
        response = self.client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2  # noqa: PLR2004

        # Verify we have stories from both users
        usernames = {story["user"]["username"] for story in results}
        assert "user1" in usernames
        assert "user2" in usernames
