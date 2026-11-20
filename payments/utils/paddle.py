from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from paddle_billing import Client
from paddle_billing import Environment
from paddle_billing import Options


def get_paddle_client() -> Client:
    """Return a Paddle client. DEBUG uses the sandbox, otherwise production."""
    api_key = settings.PADDLE_API_KEY.strip()
    if not api_key:
        msg = "PADDLE_API_KEY is not set"
        raise ImproperlyConfigured(msg)
    environment = Environment.SANDBOX if settings.DEBUG else Environment.PRODUCTION
    return Client(api_key, options=Options(environment))
