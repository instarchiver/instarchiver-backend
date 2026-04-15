from rest_framework.pagination import CursorPagination
from rest_framework.pagination import PageNumberPagination


class InstagramUserCursorPagination(CursorPagination):
    """
    Cursor pagination for Instagram User list.
    Orders by created_at (descending) with username as tie-breaker for stability.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-created_at"  # Most recent users first
    cursor_query_param = "cursor"


class StoryCursorPagination(CursorPagination):
    """
    Cursor pagination for Story list.
    Orders by created_at (descending) for most recent stories first.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-created_at"  # Most recent stories first
    cursor_query_param = "cursor"


class InstagramUserHistoryCursorPagination(CursorPagination):
    """
    Cursor pagination for Instagram User history records.
    Orders by history_date (descending) to show most recent changes first.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-history_date"  # Most recent history records first
    cursor_query_param = "cursor"


class PostCursorPagination(CursorPagination):
    """
    Cursor pagination for Post list.
    Orders by created_at (descending) for most recent posts first.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-created_at"  # Most recent posts first
    cursor_query_param = "cursor"


class PostAISearchCursorPagination(CursorPagination):
    """
    Cursor pagination for AI-powered post search.
    Orders by similarity_score (descending) for most relevant posts first.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-similarity_score"  # Most similar posts first
    cursor_query_param = "cursor"


class UserFollowCursorPagination(CursorPagination):
    """
    Cursor pagination for UserFollow list (followers / following).
    Orders by first_seen_at (descending) to show most recently observed first.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-first_seen_at"
    cursor_query_param = "cursor"


class PostSimilarPageNumberPagination(PageNumberPagination):
    """
    Page number pagination for similar posts.
    Returns posts ordered by similarity score (descending).
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class StorySimilarPageNumberPagination(PageNumberPagination):
    """
    Page number pagination for similar stories.
    Returns stories ordered by similarity score (descending).
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
