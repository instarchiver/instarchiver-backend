from rest_framework import serializers

from payments.models import PricingFeature
from payments.models import PricingPlan


class PricingFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingFeature
        fields = ("id", "label", "is_available", "sort_order")


class PricingPlanSerializer(serializers.ModelSerializer):
    features = PricingFeatureSerializer(many=True, read_only=True)

    class Meta:
        model = PricingPlan
        fields = (
            "id",
            "name",
            "description",
            "billing_period",
            "price",
            "currency",
            "features",
            "sort_order",
        )
