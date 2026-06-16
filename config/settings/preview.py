import os

# Provide safe defaults for vars that production.py requires but preview doesn't use
os.environ.setdefault("MAILGUN_API_KEY", "preview-noop")
os.environ.setdefault("MAILGUN_DOMAIN", "preview.instarchiver.net")
os.environ.setdefault("SENTRY_DSN", "")
os.environ.setdefault("DJANGO_ADMIN_URL", "admin/")

from .production import *  # noqa: F403
from .production import INSTALLED_APPS as _INSTALLED_APPS

# No Mailgun in preview environments — console output is sufficient
INSTALLED_APPS = [app for app in _INSTALLED_APPS if app != "anymail"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Dynamic CSRF trusted origins based on the preview subdomain
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]  # noqa: F405

# Traefik terminates TLS; Django receives plain HTTP internally
SECURE_SSL_REDIRECT = False
