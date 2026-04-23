from django.urls import path

from instagram.views import InstagramStatisticView
from instagram.views import InstagramUserAddStoryCreditAPIView
from instagram.views import InstagramUserDetailView
from instagram.views import InstagramUserHistoryView
from instagram.views import InstagramUserListCreateView
from instagram.views import PostAISearchView
from instagram.views import PostDetailView
from instagram.views import PostListView
from instagram.views import PostSimilarView
from instagram.views import ProcessInstagramDataView
from instagram.views import StoryDetailView
from instagram.views import StoryListView
from instagram.views import StorySimilarView

app_name = "instagram"
urlpatterns = [
    path("users/", InstagramUserListCreateView.as_view(), name="user_list"),
    path("users/<uuid:uuid>/", InstagramUserDetailView.as_view(), name="user_detail"),
    path(
        "users/<uuid:uuid>/add-story-credit/",
        InstagramUserAddStoryCreditAPIView.as_view(),
        name="user_add_story_credit",
    ),
    path("stories/", StoryListView.as_view(), name="story_list"),
    path("stories/<str:story_id>/", StoryDetailView.as_view(), name="story_detail"),
    path(
        "stories/<str:story_id>/similar/",
        StorySimilarView.as_view(),
        name="story_similar",
    ),
    path("posts/", PostListView.as_view(), name="post_list"),
    path("posts/ai-search/", PostAISearchView.as_view(), name="post_ai_search"),
    path("posts/<str:id>/", PostDetailView.as_view(), name="post_detail"),
    path("posts/<str:id>/similar/", PostSimilarView.as_view(), name="post_similar"),
    path(
        "users/<uuid:uuid>/history/",
        InstagramUserHistoryView.as_view(),
        name="user_history",
    ),
    path("inject-data/", ProcessInstagramDataView.as_view(), name="process_data"),
    path("statistic/", InstagramStatisticView.as_view(), name="statistic"),
]
