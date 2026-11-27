from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from settings.models import FrontendSetting
from settings.serializers import FrontendSettingSerializer


@method_decorator(never_cache, name="dispatch")
class FrontendSettingView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = FrontendSettingSerializer

    @extend_schema(
        summary="Get frontend feature toggles",
        description="Return public feature flags that control frontend capabilities.",
        responses={200: FrontendSettingSerializer},
    )
    def get(self, request: Request) -> Response:
        return Response(self.serializer_class(FrontendSetting.get_solo()).data)
