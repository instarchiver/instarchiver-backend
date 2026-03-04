from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from instagram.tests.factories import PostFactory


class PostAISearchViewTest(TestCase):
    """Tests for the PostAISearchView endpoint."""

    def setUp(self):
        """Set up test client and URL."""
        self.client = APIClient()
        self.url = reverse("instagram:post_ai_search")

    def test_missing_text_param_returns_400(self):
        """Test that GET without 'text' parameter returns 400."""
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data

    def test_empty_text_param_returns_400(self):
        """Test that GET with empty 'text' parameter returns 400."""
        response = self.client.get(self.url, {"text": ""})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("instagram.views.posts.generate_text_embedding")
    def test_search_with_text_returns_200(self, mock_embed):
        """Test that a valid 'text' param returns a 200 with results."""
        mock_embed.return_value = ([0.1] * 1536, 10)
        PostFactory.create_batch(3)
        response = self.client.get(self.url, {"text": "beautiful sunset"})
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data

    @patch("instagram.views.posts.generate_text_embedding")
    def test_unauthenticated_access_allowed(self, mock_embed):
        """Test that unauthenticated access is allowed (IsAuthenticatedOrReadOnly)."""
        mock_embed.return_value = ([0.0] * 1536, 0)
        response = self.client.get(self.url, {"text": "query"})
        assert response.status_code == status.HTTP_200_OK

    @patch("instagram.views.posts.generate_text_embedding")
    def test_returns_only_posts_with_embeddings(self, mock_embed):
        """Test that only posts with embeddings are returned."""
        mock_embed.return_value = ([0.1] * 1536, 10)
        # Posts with embeddings
        PostFactory(embedding=[0.1] * 1536)
        PostFactory(embedding=[0.2] * 1536)
        # Post without embedding
        PostFactory(embedding=None)

        response = self.client.get(self.url, {"text": "photo"})
        assert response.status_code == status.HTTP_200_OK
        # Only the 2 posts created with embeddings (lines 51-52) are returned
        assert len(response.data["results"]) == 2  # noqa: PLR2004
