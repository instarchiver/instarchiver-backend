from unittest.mock import MagicMock
from unittest.mock import patch

from django.test import TestCase

from core.utils import openrouter
from settings.models import OpenRouterSetting

CATEGORIES = ["stories", "post", "highlight", "unknown"]

SAMPLE_RESPONSE = {
    "id": "gen-dec-1790268295-yiQU7nr8t45UGvkdiGbt",
    "answers": {
        "classification": {
            "type": "score",
            "score": 2.96,
            "legend": {"0": "stories", "1": "post", "2": "highlight", "3": "unknown"},
            "probabilities": {"0": 0, "1": 0.02, "2": 0, "3": 0.98},
            "confidence": 0.96,
        },
    },
    "usage": {"input_tokens": 309, "output_tokens": 20, "cost": 0.000012978},
}


@patch("core.utils.openrouter.requests.post")
class TestClassify(TestCase):
    def setUp(self):
        setting = OpenRouterSetting.get_solo()
        setting.embedding_api_key = "sk-or-test"
        setting.save()

    def test_returns_category_with_highest_probability(self, mock_post):
        mock_post.return_value = MagicMock(json=MagicMock(return_value=SAMPLE_RESPONSE))

        category = openrouter.classify("https://chatgpt.com/", "Which?", CATEGORIES)

        assert category == "unknown"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["state"] == "https://chatgpt.com/"
        assert payload["questions"]["classification"]["criteria"] == CATEGORIES
