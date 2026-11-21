"""HTTP client for the documented Integration Gateway API.

Only the documented endpoints are used:

* ``POST /events``          submit an event
* ``GET  /events/{id}``     read an event's status

Only the documented headers are sent. The token is read from settings and is
never logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

import requests

from .config import SOURCE_SYSTEM, gateway_url, hr_token, http_timeout

MAX_STORED_BODY = 2000

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429})


@dataclass(frozen=True)
class GatewayResponse:
    """A normalized gateway result, including whether a retry is safe."""

    http_status: int | None
    gateway_status: str | None = None
    event_id: str | None = None
    body: dict | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_fields: dict | None = None
    retryable: bool = False
    retry_after: float | None = None
    transport_error: str | None = None


def _json_body(response) -> dict | None:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    return body if isinstance(body, dict) else None


def _response_text(response) -> str:
    text = getattr(response, "text", "") or ""
    return text[:MAX_STORED_BODY]


def _retry_after(response) -> float | None:
    headers = getattr(response, "headers", None) or {}
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, seconds)


def _classify(response, expected_event_id: str | None = None) -> GatewayResponse:
    status_code = getattr(response, "status_code", None)
    body = _json_body(response)
    retry_after = _retry_after(response)

    if status_code is not None and 200 <= status_code < 300:
        gateway_status = body.get("status") if body else None
        returned_event_id = body.get("event_id") if body else None
        if (
            expected_event_id
            and returned_event_id
            and str(returned_event_id) != str(expected_event_id)
        ):
            return GatewayResponse(
                http_status=status_code,
                gateway_status=gateway_status,
                event_id=str(returned_event_id),
                body=body,
                error_code="event_id_mismatch",
                error_message=(
                    "gateway returned event_id %s for request %s"
                    % (returned_event_id, expected_event_id)
                ),
                retryable=False,
            )
        return GatewayResponse(
            http_status=status_code,
            gateway_status=gateway_status,
            event_id=str(returned_event_id) if returned_event_id else None,
            body=body,
            retryable=False,
        )

    error_code = body.get("code") if body else None
    error_message = body.get("message") if body else None
    error_fields = body.get("fields") if body else None
    if not isinstance(error_fields, dict):
        error_fields = None
    if not error_code:
        error_code = "http_%s" % status_code if status_code else "transport_error"
    if not error_message:
        error_message = _response_text(response) or "gateway request failed"

    retryable = bool(
        status_code is None
        or status_code >= 500
        or status_code in RETRYABLE_STATUS_CODES
    )
    return GatewayResponse(
        http_status=status_code,
        body=body,
        error_code=str(error_code),
        error_message=str(error_message),
        error_fields=error_fields,
        retryable=retryable,
        retry_after=retry_after,
    )


class GatewayClient:
    """Small, testable wrapper around the gateway contract."""

    def __init__(self, *, base_url=None, token=None, timeout=None, session=None):
        self.base_url = (base_url or gateway_url()).rstrip("/")
        self._token = token if token is not None else hr_token()
        self.timeout = timeout if timeout is not None else http_timeout()
        self.session = session or requests.Session()

    def _headers(self) -> dict:
        # The contract requires all four headers on every request.
        return {
            "Authorization": "Bearer %s" % self._token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Limbus-System": SOURCE_SYSTEM,
        }

    def post_event(self, envelope: dict) -> GatewayResponse:
        """Submit one EventEnvelope with Idempotency-Key == event_id."""
        event_id = str(envelope["event_id"])
        headers = self._headers()
        headers["Idempotency-Key"] = event_id
        url = "%s/events" % self.base_url
        try:
            response = self.session.post(
                url, json=envelope, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            return GatewayResponse(
                http_status=None,
                error_code="transport_error",
                error_message=str(exc) or exc.__class__.__name__,
                retryable=True,
                transport_error=exc.__class__.__name__,
            )
        return _classify(response, expected_event_id=event_id)

    def get_event(self, event_id: str) -> GatewayResponse:
        """Read the gateway's status for an event (documented GET)."""
        headers = self._headers()
        url = "%s/events/%s" % (self.base_url, quote(str(event_id), safe=""))
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            return GatewayResponse(
                http_status=None,
                error_code="transport_error",
                error_message=str(exc) or exc.__class__.__name__,
                retryable=True,
                transport_error=exc.__class__.__name__,
            )
        return _classify(response, expected_event_id=str(event_id))


def response_body_text(response: GatewayResponse) -> str | None:
    """Serialize a response body for the audit trail, capped in size."""
    if response.body is not None:
        text = json.dumps(response.body, sort_keys=True, ensure_ascii=False)
    else:
        text = response.transport_error or ""
    text = text[:MAX_STORED_BODY]
    return text or None
