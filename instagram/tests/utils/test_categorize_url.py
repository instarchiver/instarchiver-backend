from unittest.mock import patch

from instagram.constants import INSTAGRAM_URL_CATEGORIES
from instagram.constants import URL_CATEGORY_POST
from instagram.constants import URL_CATEGORY_STORY
from instagram.constants import URL_CATEGORY_UNKNOWN
from instagram.utils import categorize_instagram_url


@patch("instagram.utils.classify", return_value=URL_CATEGORY_POST)
def test_categorize_instagram_url_uses_instagram_categories(mock_classify):
    url = "https://www.instagram.com/p/C1a2b3c4d5e/"

    assert categorize_instagram_url(url) == URL_CATEGORY_POST
    kwargs = mock_classify.call_args.kwargs
    assert kwargs["state"] == url
    assert kwargs["categories"] == [
        URL_CATEGORY_STORY,
        URL_CATEGORY_POST,
        URL_CATEGORY_UNKNOWN,
    ]
    assert kwargs["categories"] is INSTAGRAM_URL_CATEGORIES
