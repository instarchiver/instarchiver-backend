import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from paddle_billing import Environment

from payments.utils import get_paddle_client


@override_settings(DEBUG=True, PADDLE_API_KEY="pdl_test_key")
def test_debug_uses_sandbox():
    assert get_paddle_client().options.environment == Environment.SANDBOX


@override_settings(DEBUG=False, PADDLE_API_KEY="pdl_test_key")
def test_no_debug_uses_production():
    assert get_paddle_client().options.environment == Environment.PRODUCTION


@pytest.mark.parametrize("api_key", ["", "  \n"])
def test_missing_key_raises(api_key):
    with override_settings(PADDLE_API_KEY=api_key), pytest.raises(ImproperlyConfigured):
        get_paddle_client()
