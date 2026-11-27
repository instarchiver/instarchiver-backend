from django.urls import path

from settings.views import FrontendSettingView

app_name = "settings"
urlpatterns = [
    path("frontend/", FrontendSettingView.as_view(), name="frontend"),
]
