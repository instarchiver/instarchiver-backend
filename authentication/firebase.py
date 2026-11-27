import hashlib
import json
import threading
from typing import Any

import firebase_admin
from django.core.exceptions import ImproperlyConfigured
from firebase_admin import auth
from firebase_admin import credentials

_app_lock = threading.Lock()


def _get_service_account_json() -> str:
    """Return the configured Firebase service account JSON string."""
    try:
        from settings.models import FirebaseAdminSetting  # noqa: PLC0415
    except ImportError as e:
        msg = "FirebaseAdminSetting model not found"
        raise ImproperlyConfigured(msg) from e

    try:
        firebase_settings = FirebaseAdminSetting.get_solo()
    except Exception as e:
        msg = "Cannot access Firebase settings"
        raise ImproperlyConfigured(msg) from e

    raw_json = firebase_settings.service_account_json
    if not isinstance(raw_json, str) or not raw_json.strip():
        msg = "Firebase service account JSON content not configured"
        raise ImproperlyConfigured(msg)

    return raw_json


def _get_firebase_app() -> firebase_admin.App:
    """Return a cached Firebase App keyed by the service account JSON hash."""
    service_account_json = _get_service_account_json()
    digest = hashlib.sha256(service_account_json.encode("utf-8")).hexdigest()
    app_name = f"firebase-{digest}"

    try:
        return firebase_admin.get_app(app_name)
    except ValueError:
        pass

    with _app_lock:
        try:
            return firebase_admin.get_app(app_name)
        except ValueError:
            pass

        try:
            service_account_data = json.loads(service_account_json)
        except (json.JSONDecodeError, TypeError) as e:
            msg = "Invalid Firebase service account JSON content"
            raise ImproperlyConfigured(msg) from e

        if not isinstance(service_account_data, dict):
            msg = "Invalid Firebase service account JSON content"
            raise ImproperlyConfigured(msg)

        try:
            cred = credentials.Certificate(service_account_data)
        except (ValueError, TypeError) as e:
            msg = "Invalid Firebase service account JSON content"
            raise ImproperlyConfigured(msg) from e

        # Keep old named apps alive so concurrent requests on other threads do not fail.
        return firebase_admin.initialize_app(cred, name=app_name)


def validate_token(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token and return its decoded claims.

    Args:
        token: Firebase ID token string.

    Returns:
        Decoded token payload containing claims such as uid and email.

    Raises:
        Exception: If token verification fails.
    """
    app = _get_firebase_app()
    try:
        return auth.verify_id_token(token, app=app)
    except Exception as e:
        msg = "Invalid token"
        raise Exception(msg) from e  # noqa: TRY002


def get_user_info(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token and extract user details from its claims.

    Args:
        token: Firebase ID token string.

    Returns:
        Dictionary with uid, email, email_verified, name, and photo_url.

    Raises:
        ValueError: If the verified token has no non-empty uid claim.
        Exception: If token verification fails.
    """
    app = _get_firebase_app()
    # Keep check_revoked=False: True invokes auth.get_user synchronously.
    decoded_token = auth.verify_id_token(token, app=app)

    raw_uid = decoded_token.get("uid")
    uid = raw_uid.strip() if isinstance(raw_uid, str) else ""
    if not uid:
        msg = "Token missing uid claim"
        raise ValueError(msg)

    raw_email = decoded_token.get("email")
    email = raw_email.strip() if isinstance(raw_email, str) else ""
    raw_name = decoded_token.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    raw_picture = decoded_token.get("picture")
    photo_url = raw_picture.strip() if isinstance(raw_picture, str) else ""

    return {
        "uid": uid,
        "email": email or None,
        "email_verified": decoded_token.get("email_verified") is True,
        "name": name,
        "photo_url": photo_url,
    }
