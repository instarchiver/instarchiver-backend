from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.test import APITestCase

from payments.tests.factories import PricingFeatureFactory
from payments.tests.factories import PricingPlanFactory


class PricingPlanListViewTest(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("payments:pricing-plan-list")
        cache.clear()

    def test_no_authentication_required(self):
        """Test that unauthenticated clients can access the endpoint."""
        response = self.client.get(self.url)
        assert response.status_code == 200  # noqa: PLR2004

    def test_empty_when_no_plans(self):
        """Test that an empty list is returned when no plans exist."""
        response = self.client.get(self.url)
        assert response.status_code == 200  # noqa: PLR2004
        assert response.data == []

    def test_returns_active_plans_only(self):
        """Test that only active plans are returned."""
        active = PricingPlanFactory()
        PricingPlanFactory(inactive=True)

        response = self.client.get(self.url)

        assert response.status_code == 200  # noqa: PLR2004
        assert len(response.data) == 1
        assert response.data[0]["id"] == active.id

    def test_features_nested_in_response(self):
        """Test that features are returned nested under each plan."""
        plan = PricingPlanFactory()
        feature = PricingFeatureFactory(plan=plan, label="Unlimited storage")

        response = self.client.get(self.url)

        assert response.status_code == 200  # noqa: PLR2004
        assert len(response.data[0]["features"]) == 1
        assert response.data[0]["features"][0]["id"] == feature.id
        assert response.data[0]["features"][0]["label"] == "Unlimited storage"

    def test_response_is_cached(self):
        """Test that the second request is served from cache."""
        PricingPlanFactory()

        with patch("payments.views.pricings.cache.get", wraps=cache.get) as mock_get:
            self.client.get(self.url)
            self.client.get(self.url)
            # Second call should have retrieved a cached value (not None)
            assert mock_get.call_count == 2  # noqa: PLR2004
            last_return = mock_get.return_value
            assert last_return is not None

    def test_serializer_fields(self):
        """Test that only the expected fields are present in the response."""
        PricingPlanFactory()

        response = self.client.get(self.url)

        expected_fields = {
            "id",
            "name",
            "description",
            "billing_period",
            "price",
            "currency",
            "features",
            "sort_order",
        }
        assert set(response.data[0].keys()) == expected_fields
