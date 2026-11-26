from django.db import connections
from django.db import transaction
from django.db.models import QuerySet
from django.db.models.query import EmptyQuerySet
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param
from rest_framework.utils.urls import replace_query_param


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


class SimilarPagination(PageNumberPagination):
    """Non-counting page pagination capped at top-K results for similarity views.

    Avoids COUNT(*) scans across embedded rows and enables pgvector's
    strict_order iterative HNSW scan inside a short transaction block so
    filtered and deep-page lookups return ordered results without drift.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    max_results = 200
    template = None

    def to_html(self) -> str:
        """Disable browsable API pagination controls."""
        return ""

    def _fetch_postgres_slice(self, queryset, offset, fetch_limit):
        conn = connections[queryset.db]
        was_in_atomic = conn.in_atomic_block
        prev_iterative = None
        if was_in_atomic:
            with conn.cursor() as cursor:
                cursor.execute("SELECT current_setting('hnsw.iterative_scan', true)")
                row = cursor.fetchone()
                prev_iterative = row[0] if row else None

        with transaction.atomic(using=queryset.db):
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('hnsw.iterative_scan', 'strict_order', true)",
                )
            items = list(queryset[offset : offset + fetch_limit])

        # Savepoint rollback already reverts set_config(..., true); only restore
        # on normal exit so an outer atomic block does not keep strict_order.
        if was_in_atomic:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('hnsw.iterative_scan', %s, true)",
                    [prev_iterative or "off"],
                )
        return items

    def paginate_queryset(self, queryset, request, view=None):
        """Slice up to max_results items without running a COUNT(*) query."""
        self.request = request
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        raw_page = request.query_params.get(self.page_query_param)
        if raw_page in (None, ""):
            page_number = 1
        else:
            try:
                page_number = int(raw_page)
            except (TypeError, ValueError) as exc:
                msg = self.invalid_page_message.format(
                    page_number=raw_page,
                    message=str(exc),
                )
                raise NotFound(msg) from exc
            if page_number < 1:
                msg = self.invalid_page_message.format(
                    page_number=page_number,
                    message="Page number must be >= 1",
                )
                raise NotFound(msg)

        offset = (page_number - 1) * page_size
        if offset >= self.max_results:
            msg = self.invalid_page_message.format(
                page_number=page_number,
                message="Page exceeds result limit",
            )
            raise NotFound(msg)

        if isinstance(queryset, EmptyQuerySet):
            if page_number > 1:
                msg = self.invalid_page_message.format(
                    page_number=page_number,
                    message="That page contains no results",
                )
                raise NotFound(msg)
            self.page_number = 1
            self.has_next = False
            return []

        remaining = self.max_results - offset
        can_have_next = remaining > page_size
        fetch_limit = page_size + 1 if can_have_next else remaining

        if (
            isinstance(queryset, QuerySet)
            and connections[queryset.db].vendor == "postgresql"
        ):
            items = self._fetch_postgres_slice(queryset, offset, fetch_limit)
        else:
            items = list(queryset[offset : offset + fetch_limit])

        if page_number > 1 and not items:
            msg = self.invalid_page_message.format(
                page_number=page_number,
                message="That page contains no results",
            )
            raise NotFound(msg)

        self.page_number = page_number
        self.has_next = can_have_next and len(items) > page_size
        return items[:page_size]

    def get_next_link(self):
        """Return URL for the next page, or None if no further results remain."""
        if not self.has_next:
            return None
        url = self.request.build_absolute_uri()
        return replace_query_param(url, self.page_query_param, self.page_number + 1)

    def get_previous_link(self):
        """Return URL for the previous page, or None on the first page."""
        if self.page_number <= 1:
            return None
        url = self.request.build_absolute_uri()
        if self.page_number == 2:  # noqa: PLR2004
            return remove_query_param(url, self.page_query_param)
        return replace_query_param(url, self.page_query_param, self.page_number - 1)

    def get_paginated_response(self, data):
        """Return paginated response payload without total count."""
        return Response(
            {
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            },
        )

    def get_paginated_response_schema(self, schema):
        """Return OpenAPI schema matching the non-counting response."""
        return {
            "type": "object",
            "required": ["results"],
            "properties": {
                "next": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": (
                        f"http://api.example.org/accounts/?{self.page_query_param}=4"
                    ),
                },
                "previous": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "example": (
                        f"http://api.example.org/accounts/?{self.page_query_param}=2"
                    ),
                },
                "results": schema,
            },
        }
