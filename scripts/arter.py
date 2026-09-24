from instagram.utils import categorize_instagram_url  # noqa: INP001

SAMPLE_URLS = [
    "https://www.instagram.com/stories/natgeo/3864373243738778145/",
    "https://www.instagram.com/p/C1a2b3c4d5e/",
    "https://www.instagram.com/reel/C1a2b3c4d5e/",
    "https://www.instagram.com/stories/highlights/17954206126712345/",
    "https://www.instagram.com/reels/audio/1234567890123456/",
    "https://www.instagram.com/natgeo/",
    "https://chatgpt.com/",
]


def run():
    for url in SAMPLE_URLS:
        print(categorize_instagram_url(url), ": ", url)  # noqa: T201
