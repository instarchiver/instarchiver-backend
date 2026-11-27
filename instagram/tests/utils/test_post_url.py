import pytest

from instagram.utils import normalize_instagram_post_url
from instagram.utils import shortcode_to_media_id
from instagram.utils import validate_instagram_username


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (
            "https://www.instagram.com/p/C_abc123-/?utm_source=ig_web_copy_link",
            ("https://www.instagram.com/p/C_abc123-/", "C_abc123-"),
        ),
        (
            "http://instagram.com/reel/Cx1a2b3c#frag",
            ("https://www.instagram.com/reel/Cx1a2b3c/", "Cx1a2b3c"),
        ),
        (
            "https://m.instagram.com/reels/Cx1a2b3c/",
            ("https://www.instagram.com/reels/Cx1a2b3c/", "Cx1a2b3c"),
        ),
        (
            "https://instagr.am/tv/TV_99/",
            ("https://www.instagram.com/tv/TV_99/", "TV_99"),
        ),
        (
            "https://www.instagram.com/Alice.Example/p/AbC123/",
            ("https://www.instagram.com/Alice.Example/p/AbC123/", "AbC123"),
        ),
        (
            "https://www.instagram.com/bob_1/tv/TvCode1/",
            ("https://www.instagram.com/bob_1/tv/TvCode1/", "TvCode1"),
        ),
        (
            "https://www.instagram.com/share/BA12345678/",
            ("https://www.instagram.com/share/BA12345678/", None),
        ),
        (
            "https://www.instagram.com/share/p/BA12345678",
            ("https://www.instagram.com/share/p/BA12345678/", None),
        ),
        (
            "https://www.instagram.com/share/reel/BA12345678/",
            ("https://www.instagram.com/share/reel/BA12345678/", None),
        ),
    ],
)
def test_normalize_instagram_post_url_valid(raw_url, expected):
    assert normalize_instagram_post_url(raw_url) == expected


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "   ",
        "ftp://www.instagram.com/p/AbC123/",
        "https://evil.com/p/AbC123/",
        "https://user:pass@www.instagram.com/p/AbC123/",
        "https://www.instagram.com:8443/p/AbC123/",
        "https://www.instagram.com/stories/alice/123/",
        "https://www.instagram.com/reels/audio/123/",
        "https://www.instagram.com/alice/",
        "https://www.instagram.com/../p/AbC123/",
        "https://www.instagram.com/./p/AbC123/",
        "https://www.instagram.com/explore/p/AbC123/",
        "https://www.instagram.com/share/stories/",
        "https://www.instagram.com/p/AbC123\n/",
    ],
)
def test_normalize_instagram_post_url_rejects_invalid(bad_url):
    with pytest.raises(ValueError, match=r"."):
        normalize_instagram_post_url(bad_url)


def test_shortcode_to_media_id():
    assert shortcode_to_media_id("B") == "1"
    assert shortcode_to_media_id("Df4Cd5oH9Gv") == "4032984317144584623"
    assert shortcode_to_media_id("C_abc123-") is not None
    assert shortcode_to_media_id("") is None
    assert shortcode_to_media_id("A" * 29) is None
    assert shortcode_to_media_id("bad/char") is None


def test_validate_instagram_username():
    assert validate_instagram_username(" @Alice.Doe_1 ") == "alice.doe_1"
    assert validate_instagram_username("@@alice") is None
    assert validate_instagram_username("../admin") is None
    assert validate_instagram_username("alice..bob") is None
    assert validate_instagram_username("stories") is None
    assert validate_instagram_username(123) is None
