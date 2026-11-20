from django.urls import path

from tools.views import InstagramProfileDetailAPIView

app_name = "tools"
urlpatterns = [
    path(
        "instagram/profile/",
        InstagramProfileDetailAPIView.as_view(),
        name="instagram_profile_detail",
    ),
]
