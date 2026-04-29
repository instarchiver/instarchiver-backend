"""
With these settings, tests run faster.
"""

from .base import *  # noqa: F403
from .base import TEMPLATES
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="eAMtDVye7WORWiScuSjOEJjCWH1PKCNsHm0FaaxceGmJYj5ssML29TwnilVrUC7N",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# CACHES
# ------------------------------------------------------------------------------
# Use the prometheus-instrumented locmem cache in tests, consistent with local
# development, so that cache metrics are exercised during the test run.
CACHES = {
    "default": {
        "BACKEND": "django_prometheus.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "http://media.testserver/"

# DATABASES
# ------------------------------------------------------------------------------
# Bypass PgBouncer for tests: the test runner creates/drops test_* databases,
# which PgBouncer cannot proxy (it is configured for a single database name).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": env("POSTGRES_HOST", default="postgres"),
        "PORT": env.int("POSTGRES_PORT", default=5432),
        "NAME": env("POSTGRES_DB", default="core"),
        "USER": env("POSTGRES_USER", default=""),
        "PASSWORD": env("POSTGRES_PASSWORD", default=""),
        "ATOMIC_REQUESTS": True,
    },
}
# Your stuff...
# ------------------------------------------------------------------------------
