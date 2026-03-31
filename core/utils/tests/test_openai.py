from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.test import TestCase

from core.utils.openai import generate_text_embedding
from core.utils.openai import moderate_image_content


class TestGenerateTextEmbedding(TestCase):
    """Tests for the generate_text_embedding utility function."""

    @patch("core.utils.openai.get_openai_client")
    def test_generate_text_embedding_success(self, mock_get_client):
        """Test successful embedding generation."""
        # Mock OpenAI client and response
        mock_client = Mock()
        mock_response = Mock()
        mock_embedding_data = Mock()
        mock_embedding_data.embedding = [0.1] * 1536  # 1536-dimensional vector
        mock_response.data = [mock_embedding_data]
        mock_response.usage = Mock()
        mock_response.usage.total_tokens = 100
        mock_client.embeddings.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Test embedding generation
        text = "This is a test caption for embedding generation"
        embedding, token_usage = generate_text_embedding(text)

        # Verify the result
        assert len(embedding) == 1536  # noqa: PLR2004
        assert all(isinstance(x, float) for x in embedding)

        # Verify the client was called correctly
        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=text,
        )

    @patch("core.utils.openai.get_openai_client")
    def test_generate_text_embedding_empty_text(self, mock_get_client):
        """Test that empty text raises ValueError."""
        with pytest.raises(ValueError, match="Text cannot be empty"):
            generate_text_embedding("")

        with pytest.raises(ValueError, match="Text cannot be empty"):
            generate_text_embedding("   ")

        # Verify client was never called
        mock_get_client.assert_not_called()

    @patch("core.utils.openai.get_openai_client")
    def test_generate_text_embedding_api_error(self, mock_get_client):
        """Test error handling when OpenAI API fails."""
        # Mock API error
        mock_client = Mock()
        mock_client.embeddings.create.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        # Test that exception is raised
        with pytest.raises(Exception, match="API Error"):
            generate_text_embedding("Test text")

    @patch("core.utils.openai.get_openai_client")
    def test_generate_text_embedding_dimensions(self, mock_get_client):
        """Test that embedding has correct dimensions."""
        # Mock OpenAI client and response with specific dimensions
        mock_client = Mock()
        mock_response = Mock()
        mock_embedding_data = Mock()
        test_embedding = [0.5] * 1536
        mock_embedding_data.embedding = test_embedding
        mock_response.data = [mock_embedding_data]
        mock_response.usage = Mock()
        mock_response.usage.total_tokens = 100
        mock_client.embeddings.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Generate embedding
        embedding, token_usage = generate_text_embedding("Test text")

        # Verify dimensions
        assert len(embedding) == 1536  # noqa: PLR2004
        assert embedding == test_embedding

    @patch("core.utils.openai.get_openai_client")
    def test_generate_text_embedding_with_long_text(self, mock_get_client):
        """Test embedding generation with long text."""
        # Mock OpenAI client and response
        mock_client = Mock()
        mock_response = Mock()
        mock_embedding_data = Mock()
        mock_embedding_data.embedding = [0.2] * 1536
        mock_response.data = [mock_embedding_data]
        mock_response.usage = Mock()
        mock_response.usage.total_tokens = 100
        mock_client.embeddings.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Test with long text
        long_text = "This is a very long caption. " * 100
        embedding, token_usage = generate_text_embedding(long_text)

        # Verify the result
        assert len(embedding) == 1536  # noqa: PLR2004

        # Verify the client was called with the long text
        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=long_text,
        )


class TestModerateImageContent(TestCase):
    """Tests for the moderate_image_content utility function."""

    @patch("core.utils.openai.get_openai_client")
    def test_moderate_image_content_success(self, mock_get_client):
        """Test successful image content moderation."""
        mock_client = Mock()
        mock_response = Mock()
        mock_result = Mock()
        mock_result.dict.return_value = {
            "flagged": False,
            "categories": {"sexual": False, "violence": False},
            "category_scores": {"sexual": 0.001, "violence": 0.002},
        }
        mock_response.results = [mock_result]
        mock_client.moderations.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = moderate_image_content("https://example.com/image.jpg")

        assert isinstance(result, dict)
        assert "flagged" in result

    @patch("core.utils.openai.get_openai_client")
    def test_moderate_image_content_empty_url(self, mock_get_client):
        """Test that empty URL raises ValueError."""
        with pytest.raises(ValueError, match="Image URL cannot be empty"):
            moderate_image_content("")

        with pytest.raises(ValueError, match="Image URL cannot be empty"):
            moderate_image_content("   ")

        mock_get_client.assert_not_called()

    @patch("core.utils.openai.get_openai_client")
    def test_moderate_image_content_api_error(self, mock_get_client):
        """Test that API errors propagate."""
        mock_client = Mock()
        mock_client.moderations.create.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        with pytest.raises(Exception, match="API Error"):
            moderate_image_content("https://example.com/image.jpg")

    @patch("core.utils.openai.get_openai_client")
    def test_moderate_image_content_calls_correct_model(self, mock_get_client):
        """Test that the correct model and input format are used."""
        mock_client = Mock()
        mock_response = Mock()
        mock_result = Mock()
        mock_result.dict.return_value = {"flagged": False}
        mock_response.results = [mock_result]
        mock_client.moderations.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        image_url = "https://example.com/photo.jpg"
        moderate_image_content(image_url)

        mock_client.moderations.create.assert_called_once_with(
            model="omni-moderation-latest",
            input=[{"type": "image_url", "image_url": {"url": image_url}}],
        )
