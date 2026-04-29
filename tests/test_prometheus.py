"""Tests for the django-prometheus metrics integration."""

from django.test import TestCase
from rest_framework import status


class PrometheusMetricsEndpointTest(TestCase):
    """Test suite for the Prometheus metrics endpoint."""

    url = "/prometheus/metrics"

    def setUp(self):
        """Fetch the metrics endpoint response shared across all test methods."""
        self.response = self.client.get(self.url)
        self.content = self.response.content.decode()

    def test_metrics_endpoint_returns_200(self):
        """Test that the Prometheus metrics endpoint is accessible."""
        assert self.response.status_code == status.HTTP_200_OK

    def test_metrics_endpoint_content_type_is_text(self):
        """Test that the metrics endpoint returns a text/plain content type."""
        assert "text/plain" in self.response.get("Content-Type", "")

    def test_metrics_endpoint_contains_django_http_metrics(self):
        """Test that the metrics output includes Django HTTP request counters."""
        assert "django_http_requests_total_by_method_total" in self.content

    def test_metrics_endpoint_contains_django_cache_metrics(self):
        """Test that the metrics output includes Django cache operation counters."""
        assert "django_cache_get_total" in self.content
