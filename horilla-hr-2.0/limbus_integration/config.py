"""Configuration for the HR -> Integration Gateway connection.

Credentials and hosts come from the environment. Nothing here has a token
default, and no token is ever written to the database, logs, or source.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from django.conf import settings

# The gateway's documented enum value for this system. It is sent on every
# request as X-Limbus-System and in the event envelope's source_system.
SOURCE_SYSTEM = "hr"

# The OpenAPI document's local/private development server. This is a
# documented default, not a production host: set LIMBUS_GATEWAY_URL in every
# real deployment.
DEFAULT_GATEWAY_URL = "http://localhost:8088/api/v1/integration"


class IntegrationConfigurationError(RuntimeError):
    """The gateway connection is not configured safely enough to send."""


def gateway_url() -> str:
    """Return the validated gateway base URL, without a trailing slash."""
    value = (
        getattr(settings, "LIMBUS_GATEWAY_URL", "") or DEFAULT_GATEWAY_URL
    ).strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise IntegrationConfigurationError(
            "LIMBUS_GATEWAY_URL must be an absolute http(s) URL."
        )
    return value.rstrip("/")


def hr_token() -> str:
    """Return the HR system token, or refuse to call the gateway."""
    token = (getattr(settings, "LIMBUS_HR_TOKEN", "") or "").strip()
    if not token:
        raise IntegrationConfigurationError(
            "LIMBUS_HR_TOKEN is not configured; refusing to call the gateway."
        )
    return token


def http_timeout() -> float:
    value = getattr(settings, "LIMBUS_HTTP_TIMEOUT", 15.0)
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationConfigurationError(
            "LIMBUS_HTTP_TIMEOUT must be a number of seconds."
        ) from exc
    if timeout <= 0:
        raise IntegrationConfigurationError("LIMBUS_HTTP_TIMEOUT must be positive.")
    return timeout


def outbox_max_attempts() -> int:
    value = getattr(settings, "LIMBUS_OUTBOX_MAX_ATTEMPTS", 5)
    try:
        attempts = int(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationConfigurationError(
            "LIMBUS_OUTBOX_MAX_ATTEMPTS must be an integer."
        ) from exc
    if attempts < 1:
        raise IntegrationConfigurationError(
            "LIMBUS_OUTBOX_MAX_ATTEMPTS must be at least 1."
        )
    return attempts


def outbox_batch_size() -> int:
    value = getattr(settings, "LIMBUS_OUTBOX_BATCH_SIZE", 50)
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationConfigurationError(
            "LIMBUS_OUTBOX_BATCH_SIZE must be an integer."
        ) from exc
    if size < 1:
        raise IntegrationConfigurationError(
            "LIMBUS_OUTBOX_BATCH_SIZE must be at least 1."
        )
    return size


def auto_publish_enabled() -> bool:
    """Whether model saves should enqueue HR lifecycle events."""
    return bool(getattr(settings, "LIMBUS_AUTO_PUBLISH", True))


def verify_ssl() -> bool:
    """Whether TLS certificates are verified when calling the gateway."""
    if os.environ.get("PYTHONHTTPSVERIFY") == "0":
        return False
    return bool(getattr(settings, "LIMBUS_VERIFY_SSL", True))
