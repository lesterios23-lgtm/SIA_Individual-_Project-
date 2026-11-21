"""Handle Production events that need an accountable HR operator.

The gateway's inbound delivery contract is not published in the OpenAPI
document yet, so this module is the domain handler plus a file/stdin adapter
(``limbus_ingest_inbound``). When the gateway publishes a delivery mechanism,
only the adapter changes; the validation, idempotency and resolution below
stay the same.

The handler never invents an operator identity. An event whose operator ID is
missing, unknown or inactive becomes an HR exception for follow-up.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from datetime import timezone as datetime_timezone

from django.utils import timezone

from employee.models import Employee

from .events import normalize_external_employee_id
from .models import InboundEvent

SOURCE_SYSTEMS = frozenset(
    {"finance", "hr", "supply-chain", "sales-marketing", "production"}
)

# Production is the only system HR accepts accountability events from.
INBOUND_SOURCE_SYSTEM = "production"

ENVELOPE_FIELDS = frozenset(
    {
        "event_id",
        "source_system",
        "event_type",
        "occurred_at",
        "correlation_id",
        "external_id",
        "payload",
    }
)

# Provisional local registry. The gateway's allowlist is authoritative; an
# unknown type is stored and ignored, never guessed at.
ACCOUNTABILITY_EVENT_TYPES = frozenset(
    {
        "build.started",
        "build.completed",
        "build.cancelled",
        "qc.approved",
        "qc.rejected",
        "approval.requested",
        "approval.completed",
    }
)
IDENTITY_EVENT_TYPES = frozenset(
    {
        "employee.missing.identity",
        "employee.rejected.time",
        "operator.missing.identity",
        "operator.rejected.time",
        "time.rejected",
    }
)
REJECTED_TIME_EVENT_TYPES = frozenset(
    {
        "employee.rejected.time",
        "operator.rejected.time",
        "time.rejected",
    }
)

# Payload keys HR accepts as the operator reference, in priority order. The
# handoff calls this the "operator external ID"; employee_id is accepted
# because Production may publish either name.
OPERATOR_REFERENCE_KEYS = ("operator_external_id", "employee_id")


class InboundValidationError(ValueError):
    def __init__(self, fields: dict):
        self.fields = fields
        super().__init__("invalid inbound event envelope")


def _normalized_event_type(value: str) -> str:
    return str(value).strip().lower().replace("-", ".")


def _parse_timestamp(value) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be an ISO-8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("must include a UTC offset")
    return parsed.astimezone(datetime_timezone.utc)


def validate_envelope(data) -> dict:
    """Validate an EventEnvelope against the documented contract."""
    if not isinstance(data, dict):
        raise InboundValidationError({"envelope": "must be a JSON object"})

    errors = {}
    unexpected = set(data) - ENVELOPE_FIELDS
    if unexpected:
        errors["envelope"] = "unknown fields: %s" % ", ".join(sorted(unexpected))

    for field in ENVELOPE_FIELDS:
        if field not in data:
            errors[field] = "is required"

    event_id = data.get("event_id")
    if event_id is not None:
        try:
            uuid.UUID(str(event_id))
        except (TypeError, ValueError, AttributeError):
            errors["event_id"] = "must be a UUID"

    source_system = data.get("source_system")
    if source_system is not None and source_system not in SOURCE_SYSTEMS:
        errors["source_system"] = "must be one of: %s" % ", ".join(
            sorted(SOURCE_SYSTEMS)
        )

    for field in ("event_type", "correlation_id", "external_id"):
        value = data.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            errors[field] = "must be a non-empty string"

    if "occurred_at" in data:
        try:
            _parse_timestamp(data["occurred_at"])
        except (TypeError, ValueError) as exc:
            errors["occurred_at"] = str(exc)

    if "payload" in data and not isinstance(data["payload"], dict):
        errors["payload"] = "must be a JSON object"

    if errors:
        raise InboundValidationError(errors)
    return data


def _operator_reference(payload: dict) -> str:
    for key in OPERATOR_REFERENCE_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        normalized = normalize_external_employee_id(value)
        if normalized:
            return normalized
    return ""


def _find_employee(operator_ref: str):
    """Resolve an operator against HR's authoritative external ID.

    Exact match first. The fallback compares normalized values so a legacy
    badge_id with stray whitespace still resolves, without ever guessing a
    different employee.
    """
    if not operator_ref:
        return None
    employee = Employee.objects.filter(badge_id=operator_ref).first()
    if employee is not None:
        return employee
    employee = Employee.objects.filter(badge_id__iexact=operator_ref).first()
    if employee is not None:
        return employee
    for candidate in Employee.objects.exclude(badge_id__isnull=True).only(
        "id", "badge_id"
    ):
        if normalize_external_employee_id(candidate.badge_id) == operator_ref:
            return candidate
    return None


def _result(event: InboundEvent, *, duplicate=False) -> dict:
    return {
        "event_id": str(event.event_id),
        "correlation_id": event.correlation_id,
        "external_id": event.external_id,
        "event_type": event.event_type,
        "status": event.status,
        "resolution": event.resolution,
        "operator_external_id": event.operator_external_id,
        "resolved_employee_id": (
            event.resolved_employee_id if event.resolved_employee_id else None
        ),
        "error": event.error,
        "duplicate": duplicate,
        "received_at": event.received_at.isoformat() if event.received_at else None,
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
    }


def _validation_result(data, exc: InboundValidationError) -> dict:
    correlation_id = None
    event_id = None
    if isinstance(data, dict):
        raw_correlation = data.get("correlation_id")
        if isinstance(raw_correlation, str) and raw_correlation.strip():
            correlation_id = raw_correlation.strip()
        raw_event_id = data.get("event_id")
        try:
            event_id = str(uuid.UUID(str(raw_event_id))) if raw_event_id else None
        except (TypeError, ValueError, AttributeError):
            event_id = None
    return {
        "event_id": event_id,
        "correlation_id": correlation_id or "inbound-invalid-%s" % uuid.uuid4(),
        "external_id": data.get("external_id") if isinstance(data, dict) else None,
        "event_type": data.get("event_type") if isinstance(data, dict) else None,
        "status": "rejected",
        "resolution": "validation_error",
        "operator_external_id": None,
        "resolved_employee_id": None,
        "error": "invalid inbound event envelope",
        "fields": exc.fields,
        "duplicate": False,
        "received_at": None,
        "processed_at": None,
    }


def ingest_inbound_event(data, now=None) -> dict:
    """Validate, de-duplicate and resolve one inbound Production event."""
    now = now or timezone.now()
    try:
        envelope = validate_envelope(data)
    except InboundValidationError as exc:
        return _validation_result(data, exc)

    event_uuid = uuid.UUID(str(envelope["event_id"]))
    existing = InboundEvent.objects.filter(event_id=event_uuid).first()
    if existing is not None:
        return _result(existing, duplicate=True)

    event = InboundEvent(
        event_id=event_uuid,
        source_system=envelope["source_system"],
        event_type=envelope["event_type"].strip(),
        correlation_id=envelope["correlation_id"].strip(),
        external_id=envelope["external_id"].strip(),
        payload=envelope["payload"],
        occurred_at=_parse_timestamp(envelope["occurred_at"]),
        status=InboundEvent.STATUS_RECEIVED,
    )

    normalized_type = _normalized_event_type(event.event_type)
    try:
        operator_ref = _operator_reference(envelope["payload"])
    except ValueError as exc:
        operator_ref = ""
        event.error = "invalid operator reference: %s" % exc

    event.operator_external_id = operator_ref or None

    employee = None
    if operator_ref:
        employee = _find_employee(operator_ref)
        event.resolved_employee = employee

    if envelope["source_system"] != INBOUND_SOURCE_SYSTEM:
        event.status = InboundEvent.STATUS_IGNORED
        event.resolution = "unexpected_source"
        event.error = "HR accepts accountability events from production only"
    elif not operator_ref:
        event.status = InboundEvent.STATUS_EXCEPTION
        event.resolution = "missing_identity"
        event.error = event.error or "event has no operator external ID"
    elif employee is None:
        event.status = InboundEvent.STATUS_EXCEPTION
        event.resolution = "unknown_operator"
        event.error = "no HR employee matches operator ID %s" % operator_ref
    elif employee.is_active is False:
        event.status = InboundEvent.STATUS_EXCEPTION
        event.resolution = "inactive_operator"
        event.error = "operator %s is inactive in HR" % operator_ref
    elif normalized_type in REJECTED_TIME_EVENT_TYPES:
        event.status = InboundEvent.STATUS_EXCEPTION
        event.resolution = "rejected_time"
        event.error = "Production reported rejected time for this operator"
    elif normalized_type in IDENTITY_EVENT_TYPES:
        event.status = InboundEvent.STATUS_EXCEPTION
        event.resolution = "missing_identity"
        event.error = "Production reported a missing identity for this operator"
    elif normalized_type in ACCOUNTABILITY_EVENT_TYPES:
        event.status = InboundEvent.STATUS_PROCESSED
        event.resolution = "processed"
    else:
        event.status = InboundEvent.STATUS_IGNORED
        event.resolution = "unsupported_event_type"

    event.processed_at = now
    try:
        event.save()
    except Exception:
        # A concurrent delivery of the same event_id: return the winner.
        existing = InboundEvent.objects.filter(event_id=event_uuid).first()
        if existing is not None:
            return _result(existing, duplicate=True)
        raise
    return _result(event)


def ingest_inbound_envelopes(items, now=None) -> list[dict]:
    return [ingest_inbound_event(item, now=now) for item in items]
