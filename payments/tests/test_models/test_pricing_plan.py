from decimal import Decimal

from django.test import TestCase

from payments.models import PricingPlan
from payments.tests.factories import PricingPlanFactory


class PricingPlanModelTest(TestCase):
    """Test suite for the PricingPlan model."""

    def test_factory_creates_instance(self):
        """Test that the factory creates a pricing plan instance."""
        plan = PricingPlanFactory()

        assert isinstance(plan, PricingPlan)
        assert plan.id is not None
        assert plan.name
        assert plan.billing_period == PricingPlan.BILLING_MONTHLY
        assert isinstance(plan.price, Decimal)
        assert plan.price > 0
        assert plan.currency == PricingPlan.CURRENCY_USD
        assert isinstance(plan.features, list)
        assert plan.is_active is True
        assert plan.sort_order == 0
        assert plan.created_at is not None
        assert plan.updated_at is not None

    def test_str_representation(self):
        """Test the string representation of a pricing plan."""
        plan = PricingPlanFactory(
            name="Pro",
            billing_period=PricingPlan.BILLING_MONTHLY,
        )
        assert str(plan) == "Pro (monthly)"

    def test_str_representation_annual(self):
        """Test the string representation for annual billing."""
        plan = PricingPlanFactory(
            name="Basic",
            billing_period=PricingPlan.BILLING_ANNUAL,
        )
        assert str(plan) == "Basic (annual)"

    def test_billing_period_choices(self):
        """Test all billing period choices are valid."""
        expected = ["monthly", "annual"]
        actual = [choice[0] for choice in PricingPlan.BILLING_PERIOD_CHOICES]
        assert set(actual) == set(expected)

    def test_currency_choices(self):
        """Test all currency choices are valid."""
        expected = ["USD", "IDR", "EUR", "SGD", "GBP", "AUD"]
        actual = [choice[0] for choice in PricingPlan.CURRENCY_CHOICES]
        assert set(actual) == set(expected)

    def test_annual_trait(self):
        """Test the annual factory trait sets billing period correctly."""
        plan = PricingPlanFactory(annual=True)
        assert plan.billing_period == PricingPlan.BILLING_ANNUAL

    def test_inactive_trait(self):
        """Test the inactive factory trait sets is_active to False."""
        plan = PricingPlanFactory(inactive=True)
        assert plan.is_active is False

    def test_history_created_on_save(self):
        """Test that history is tracked on creation."""
        plan = PricingPlanFactory()
        assert plan.history.count() == 1

    def test_history_tracked_on_update(self):
        """Test that history records changes on update."""
        plan = PricingPlanFactory()
        plan.name = "Updated Name"
        plan.save()
        assert plan.history.count() == 2  # noqa: PLR2004

    def test_ordering(self):
        """Test that plans are ordered by sort_order then name."""
        PricingPlanFactory(name="Z Plan", sort_order=2)
        PricingPlanFactory(name="A Plan", sort_order=1)
        PricingPlanFactory(name="M Plan", sort_order=1)

        plans = list(PricingPlan.objects.all())
        assert plans[0].sort_order <= plans[1].sort_order
        assert plans[1].name <= plans[2].name
