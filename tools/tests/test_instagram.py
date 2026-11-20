from http import HTTPStatus
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from curl_cffi import CurlOpt
from curl_cffi.requests import exceptions as curl_exceptions
from django.test import TestCase

from settings.models import ProxySetting
from tools.constants import DEFAULT_MAX_HTML_BYTES
from tools.constants import MAX_POSITIVE_INT32
from tools.http import ProxyConfig
from tools.instagram import InstagramProfileError
from tools.instagram import _parse_count
from tools.instagram import _parse_profile_page
from tools.instagram import fetch_instagram_profile

FULL_PAGE = (
    '<meta property="og:url" content="https://www.instagram.com/udon05310531/" />'
    '<meta property="og:description" content="13,563 Followers, 6 Following, 70 Posts'
    ' - See Instagram photos and videos from 山本崇一朗 (&#064;udon05310531)" />'
    '<script>{"result":{"data":{"xig_user_by_username":{"pk":"32917698626",'
    '"polaris_ordered_timeline_connection":{"edges":[{"node":{'
    '"pk":"3009983972823876539","code":"CnFnHnHyUO7","media_type":1,'
    '"product_type":"feed","caption":{"text":"hello"},'
    '"accessibility_caption":"Photo by 山本崇一朗 on January 06, 2023.",'
    '"display_uri":"https://cdn.example/post.jpg"}}],'
    '"page_info":{"end_cursor":"x","has_next_page":true}},'
    '"id":"17841432958784712"}}}}</script>'
    '<script>{"result":{"data":{"xig_user_by_username":{"pk":"32917698626",'
    '"username":"udon05310531","full_name":"山本崇一朗","biography":"",'
    '"is_private":false,"is_verified":false,"follower_count":13563,'
    '"following_count":6,"all_media_count":null,'
    '"profile_pic_url":"https://cdn.example/pic.jpg",'
    '"bio_links":[{"title":"Site","url":"https://example.com",'
    '"link_type":"external","is_pinned":false}],"latest_reel_media":0,'
    '"lox_highlights_connection":{"edges":[{"node":{"id":"18",'
    '"title":"close friends",'
    '"cover_media_cropped_thumbnail_url":"https://cdn.example/cover.jpg"}}]},'
    '"id":"17841432958784712"}}}}</script>'
    '<script>{"props":{"id":"32917698626","gating":null}}</script>'
)

RESTRICTED_PAGE = (
    '<meta property="og:image" content="https://cdn.example/pic.jpg?a=1&amp;b=2" />'
    '<meta property="og:title" '
    'content="Kangaroom (&#064;kanga.room) &#x2022; Instagram photos and videos" />'
    '<meta property="og:url" content="https://www.instagram.com/kanga.room/" />'
    '<meta property="og:description" content="2,529 Followers, 0 Following, 108 Posts'
    ' - See Instagram photos and videos from Kangaroom (&#064;kanga.room)" />'
    '<meta content="2,529 Followers, 0 Following, 108 Posts - '
    "Kangaroom (&#064;kanga.room) on Instagram: "
    '&quot;Coliving Eksklusif\n&#x1f3e1; Kost Premium&quot;" name="description" />'
    '<script>{"result":{"data":{"xig_user_by_username":null},'
    '"extensions":{"is_final":true}}}</script>'
    '<script>{"props":{"id":"54531785167","gating":{"title":"Restricted profile",'
    '"description":"You must be 18 years old or over to see this profile",'
    '"category_id":null}},"profile_id":"54531785167"}</script>'
)

MISSING_PAGE = (
    '<title>Instagram</title><meta name="robots" content="noimageindex, noarchive">'
)


def _mock_stream_response(
    html: str,
    *,
    status_code: int = 200,
    url: str = "https://www.instagram.com/someone/",
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.url = url
    response.iter_content.return_value = [html.encode("utf-8")]
    return response


class TestParseProfilePage:
    def test_full_profile_merges_header_and_posts_tab(self):
        profile = _parse_profile_page(FULL_PAGE)
        assert profile is not None
        assert profile["id"] == "32917698626"
        assert profile["graph_api_id"] == "17841432958784712"
        assert profile["username"] == "udon05310531"
        assert profile["follower_count"] == 13563  # noqa: PLR2004
        assert profile["post_count"] == 70  # noqa: PLR2004
        assert profile["restriction"] is None
        assert profile["latest_story_timestamp"] is None
        assert profile["bio_links"] == [
            {
                "title": "Site",
                "url": "https://example.com",
                "link_type": "external",
                "is_pinned": False,
            },
        ]
        assert (
            profile["highlights"][0]["url"]
            == "https://www.instagram.com/stories/highlights/18/"
        )
        assert profile["posts"][0]["shortcode"] == "CnFnHnHyUO7"

    def test_restricted_profile_falls_back_to_meta_tags(self):
        profile = _parse_profile_page(RESTRICTED_PAGE)
        assert profile is not None
        assert profile["id"] == "54531785167"
        assert profile["username"] == "kanga.room"
        assert profile["full_name"] == "Kangaroom"
        assert profile["biography"] == "Coliving Eksklusif\n🏡 Kost Premium"
        assert profile["profile_photo_url"] == "https://cdn.example/pic.jpg?a=1&b=2"
        assert (
            profile["follower_count"],
            profile["following_count"],
            profile["post_count"],
        ) == (2529, 0, 108)
        assert (
            profile["restriction"]
            == "You must be 18 years old or over to see this profile"
        )
        assert profile["posts"] == []

    def test_missing_profile_returns_none(self):
        assert _parse_profile_page(MISSING_PAGE) is None

    def test_malformed_json_and_unexpected_nested_types_do_not_crash(self):
        html = (
            '<meta property="og:url" content="https://www.instagram.com/" />'
            '<meta property="og:description" '
            'content="10 Followers, 5 Following, 2 Posts" />'
            '<script>{"xig_user_by_username": {broken</script>'
            '<script>{"xig_user_by_username":{"pk":"1","username":"valid_user",'
            '"bio_links":[null],"polaris_ordered_timeline_connection":{"edges":'
            '[{"node":{"pk":"2","code":"abc","caption":"plain string"}}]}}}</script>'
            '<script>{"gating": broken}</script>'
        )
        profile = _parse_profile_page(html, requested_username="valid_user")
        assert profile is not None
        assert profile["username"] == "valid_user"
        assert profile["bio_links"] == []
        assert profile["posts"][0]["caption"] is None
        assert profile["restriction"] is None

    def test_og_url_host_not_used_as_username_fallback(self):
        html = (
            '<meta property="og:url" content="https://www.instagram.com/" />'
            '<meta property="og:description" '
            'content="10 Followers, 5 Following, 2 Posts" />'
        )
        profile = _parse_profile_page(html, requested_username="target_user")
        assert profile is not None
        assert profile["username"] == "target_user"

    @pytest.mark.parametrize(
        ("text", "label", "expected"),
        [
            ("2,529 Followers, 0 Following, 108 Posts", "Followers", 2529),
            ("2,529 Followers, 0 Following, 108 Posts", "Following", 0),
            ("2,529 Followers, 0 Following, 108 Posts", "Posts", 108),
            ("272M Followers, 0 Following, 714 Posts", "Followers", 272_000_000),
            ("4.35K Followers", "Followers", 4350),
            ("2.5B Followers", "Followers", MAX_POSITIVE_INT32),
            ("1.2.3 Followers", "Followers", None),
            ("no counts here", "Posts", None),
        ],
    )
    def test_parse_count(self, text, label, expected):
        assert _parse_count(text, label) == expected


class TestFetchInstagramProfile(TestCase):
    def setUp(self):
        setting = ProxySetting.get_solo()
        setting.proxy_url = "http://proxyuser:proxypass@squid:3128"
        setting.verify_ssl = False
        setting.save()

    def test_rejects_invalid_usernames(self):
        for bad_username in ("@user", "a/b", "", "x" * 31, None, 123):
            with pytest.raises(InstagramProfileError) as exc_info:
                fetch_instagram_profile(bad_username)  # type: ignore[arg-type]
            assert exc_info.value.code == "INVALID_USERNAME"
            assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST

    @patch("tools.http.Session")
    def test_uses_proxy_setting_and_disables_proxy_tls_verify_when_false(
        self,
        mock_session_cls,
    ):
        session = mock_session_cls.return_value.__enter__.return_value
        response = _mock_stream_response(
            FULL_PAGE,
            url="https://www.instagram.com/udon05310531/",
        )
        session.get.return_value = response

        profile = fetch_instagram_profile("udon05310531")

        assert profile is not None
        assert profile["username"] == "udon05310531"
        session.curl.setopt.assert_any_call(CurlOpt.PROXY_SSL_VERIFYPEER, 0)
        session.curl.setopt.assert_any_call(CurlOpt.PROXY_SSL_VERIFYHOST, 0)
        kwargs = session.get.call_args.kwargs
        assert kwargs["proxy"] == "http://proxyuser:proxypass@squid:3128"
        assert kwargs["verify"] is False
        response.close.assert_called_once()

    @patch("tools.http.Session")
    def test_explicit_none_proxy_skips_proxy_setting(self, mock_session_cls):
        session = mock_session_cls.return_value.__enter__.return_value
        session.get.return_value = _mock_stream_response(FULL_PAGE)

        fetch_instagram_profile("udon05310531", proxy=ProxyConfig())

        session.curl.setopt.assert_not_called()
        kwargs = session.get.call_args.kwargs
        assert kwargs.get("proxy") is None
        assert kwargs["verify"] is True

    @patch("tools.http.Session")
    def test_login_wall_redirect_raises_502(self, mock_session_cls):
        session = mock_session_cls.return_value.__enter__.return_value
        session.get.return_value = _mock_stream_response(
            MISSING_PAGE,
            url="https://www.instagram.com/accounts/login/?next=/someone/",
        )

        with pytest.raises(InstagramProfileError) as exc_info:
            fetch_instagram_profile("someone", proxy=ProxyConfig())

        assert exc_info.value.code == "LOGIN_WALL"
        assert exc_info.value.status_code == HTTPStatus.BAD_GATEWAY

    @patch("tools.http.Session")
    def test_http_404_returns_none_and_429_raises_rate_limited(self, mock_session_cls):
        session = mock_session_cls.return_value.__enter__.return_value
        session.get.return_value = _mock_stream_response("", status_code=404)
        assert fetch_instagram_profile("missing", proxy=ProxyConfig()) is None

        session.get.return_value = _mock_stream_response("", status_code=429)
        with pytest.raises(InstagramProfileError) as exc_info:
            fetch_instagram_profile("limited", proxy=ProxyConfig())
        assert exc_info.value.code == "RATE_LIMITED"
        assert exc_info.value.status_code == HTTPStatus.TOO_MANY_REQUESTS

    @patch("tools.http.Session")
    def test_retries_proxy_error_once_and_redacts_credentials(self, mock_session_cls):
        session = mock_session_cls.return_value.__enter__.return_value
        session.get.side_effect = curl_exceptions.ProxyError(
            "Failed connecting to http://proxyuser:proxypass@squid:3128",
        )

        with pytest.raises(InstagramProfileError) as exc_info:
            fetch_instagram_profile("someone")

        assert session.get.call_count == 2  # noqa: PLR2004
        assert "proxyuser" not in exc_info.value.message
        assert "proxypass" not in exc_info.value.message

    @patch("tools.http.Session")
    def test_ssl_error_does_not_retry(self, mock_session_cls):
        session = mock_session_cls.return_value.__enter__.return_value
        session.get.side_effect = curl_exceptions.SSLError("TLS handshake failed")

        with pytest.raises(InstagramProfileError) as exc_info:
            fetch_instagram_profile("someone", proxy=ProxyConfig())

        assert session.get.call_count == 1
        assert exc_info.value.status_code == HTTPStatus.BAD_GATEWAY

    @patch("tools.http.Session")
    def test_oversized_response_aborted_and_closed(self, mock_session_cls):
        session = mock_session_cls.return_value.__enter__.return_value
        response = MagicMock()
        response.status_code = 200
        response.url = "https://www.instagram.com/someone/"
        response.iter_content.return_value = [b"a" * (DEFAULT_MAX_HTML_BYTES + 1)]
        session.get.return_value = response

        with pytest.raises(InstagramProfileError) as exc_info:
            fetch_instagram_profile("someone", proxy=ProxyConfig())

        assert exc_info.value.code == "UPSTREAM_ERROR"
        response.close.assert_called_once()
