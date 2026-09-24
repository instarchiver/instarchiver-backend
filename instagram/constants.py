URL_CATEGORY_STORY = "story"
URL_CATEGORY_POST = "post"
URL_CATEGORY_UNKNOWN = "unknown"

INSTAGRAM_URL_CATEGORIES = [
    URL_CATEGORY_STORY,
    URL_CATEGORY_POST,
    URL_CATEGORY_UNKNOWN,
]

INSTAGRAM_URL_QUESTION = (
    "What is the category of this Instagram URL? "
    f"/stories/<username>/ and /stories/<username>/<id>/ are {URL_CATEGORY_STORY}. "
    "/p/<code>/, /<username>/p/<code>/, /reel/<code>/, /reels/<code>/, "
    f"/share/p/<code>/ and /share/reel/<code>/ are {URL_CATEGORY_POST}. "
    f"/stories/highlights/ and /reels/audio/ are {URL_CATEGORY_UNKNOWN}. "
    "Anything else, including profile pages, explore pages and non-Instagram URLs, "
    f"is {URL_CATEGORY_UNKNOWN}."
)
