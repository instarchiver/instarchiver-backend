from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView
from drf_spectacular.views import SpectacularSwaggerView
from health_check.views import HealthCheckView
from redis.asyncio import Redis as RedisClient

urlpatterns = [
    path("", RedirectView.as_view(url="/docs/", permanent=False)),
    path("prometheus/", include("django_prometheus.urls")),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # Your stuff: custom urls includes go here
    path("authentication/", include("authentication.urls")),
    path(
        "health/",
        HealthCheckView.as_view(
            checks=[
                "health_check.Cache",
                "health_check.DNS",
                "health_check.Database",
                "health_check.Mail",
                "health_check.Storage",
                # # 3rd party checks
                # "health_check.contrib.psutil.Disk",
                # "health_check.contrib.psutil.Memory",
                "health_check.contrib.celery.Ping",
                (
                    "health_check.contrib.redis.Redis",
                    {
                        "client_factory": lambda: RedisClient.from_url(
                            settings.REDIS_URL,
                        ),
                    },
                ),
            ],
        ),
    ),
    path("instagram/", include("instagram.urls")),
    path("payments/", include("payments.urls")),
    # Media files
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]
if settings.DEBUG:
    # Static file serving when using Gunicorn + Uvicorn for local web socket development
    urlpatterns += staticfiles_urlpatterns()

# API URLS
urlpatterns += [
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),
]

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
            *urlpatterns,
        ]
