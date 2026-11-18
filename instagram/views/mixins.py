import hashlib
import json

from django.core.cache import cache
from rest_framework.response import Response


class CachedListMixin:
    """Cache list responses per scheme, host and query params.

    Pagination links are built from the request host, so the host is part of
    the key. Otherwise a request with a forged Host or X-Forwarded-Host header
    could store links to another domain for every visitor.
    """

    cache_prefix: str
    cache_ttl = 30

    def get_cache_key(self, request):
        params = sorted(dict(request.query_params).items())
        key_source = json.dumps([request.build_absolute_uri("/"), params])
        md5_hash = hashlib.md5(key_source.encode(), usedforsecurity=False).hexdigest()
        return f"{self.cache_prefix}_{md5_hash}"

    def list(self, request, *args, **kwargs):
        cache_key = self.get_cache_key(request)
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            return Response(cached_response)

        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, self.cache_ttl)
        return response
