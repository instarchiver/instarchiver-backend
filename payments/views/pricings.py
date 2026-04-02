from django.core.cache import cache
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from payments.models import PricingPlan
from payments.serializers.pricings import PricingPlanSerializer

CACHE_KEY = "pricing_plan_list"
CACHE_TTL = 60 * 5  # 5 minutes


class PricingPlanListAPIView(ListAPIView):
    serializer_class = PricingPlanSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
    pagination_class = None

    def get_queryset(self):
        return PricingPlan.objects.filter(is_active=True).prefetch_related("features")

    def list(self, request, *args, **kwargs):
        cached = cache.get(CACHE_KEY)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(CACHE_KEY, response.data, CACHE_TTL)
        return response
