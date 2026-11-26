"""Build the HR event envelope and the employee payload.

Only fields documented in INTEGRATION-HANDOFF.md are published:

* employee ID and status
* department
* role / job title
* manager or approver
* start / end employment dates

The envelope itself uses exactly the OpenAPI EventEnvelope fields. Payload
values are strings (or null); the gateway must never infer an ID or a unit.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from datetime import timezone as datetime_timezone

from django.utils import timezone

from employee.models import EmployeeWorkInformation

from .config import SOURCE_SYSTEM

EVENT_TYPE_EMPLOYEE_UPSERT = "hr.employee.upsert"
EVENT_TYPE_EMPLOYEE_DEACTIVATE = "hr.employee.deactivate"

# The handoff lists the gateway's per-event endpoints as
# /events/employee-upsert and /events/employee-deactivate. The OpenAPI
# contract exposes a single /events endpoint with event_type in the envelope,
# and uses dotted event names (for example purchase.received). These are the
# HR values that map onto those two handoff endpoints.
HR_EVENT_TYPES = frozenset(
    {
        EVENT_TYPE_EMPLOYEE_UPSERT,
        EVENT_TYPE_EMPLOYEE_DEACTIVATE,
    }
)

# The envelope is additionalProperties: false in the contract. Reject anything
# else instead of silently forwarding it.
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

MAX_EXTERNAL_ID_LENGTH = 128


class MissingEmployeeIdentity(ValueError):
    """The employee has no usable external employee ID (badge_id)."""

    def __init__(self, employee_pk):
        self.employee_pk = employee_pk
        super().__init__(
            "employee %s has no external employee ID; set Employee.badge_id"
            % employee_pk
        )


def normalize_external_employee_id(value) -> str:
    """Normalize an external employee ID without changing its meaning.

    Surrounding whitespace and repeated internal whitespace are collapsed.
    Case is preserved: some HR numbering schemes are case-sensitive, so
    upper-casing here could silently point at a different employee.
    """
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if not text:
        return ""
    if len(text) > MAX_EXTERNAL_ID_LENGTH:
        raise ValueError(
            "external employee ID exceeds %s characters" % MAX_EXTERNAL_ID_LENGTH
        )
    if any(ord(character) < 32 for character in text):
        raise ValueError("external employee ID contains a control character")
    return text


def employee_external_id(employee) -> str:
    """Return the normalized external ID, or raise if HR has none."""
    external_id = normalize_external_employee_id(getattr(employee, "badge_id", None))
    if not external_id:
        raise MissingEmployeeIdentity(getattr(employee, "pk", None))
    return external_id


def default_correlation_id(employee, external_id=None) -> str:
    """Stable business-process ID for one employee's lifecycle.

    The gateway treats correlation_id as the business process ID, so every
    event about the same employee shares it. A record without an external ID
    still gets a correlation ID based on the local HR primary key, which is
    enough to trace the blocked event until badge_id is fixed.
    """
    if external_id is None:
        external_id = normalize_external_employee_id(
            getattr(employee, "badge_id", None)
        )
    if external_id:
        return "hr-employee-%s" % external_id
    return "hr-employee-pk-%s" % getattr(employee, "pk", "unknown")


def iso_date(value) -> str | None:
    """Render a date (or datetime) as an ISO-8601 date string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def iso_timestamp(value) -> str | None:
    """Render a datetime as a UTC ISO-8601 timestamp (seconds precision)."""
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, datetime_timezone.utc)
    return value.astimezone(datetime_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _id(value) -> str | None:
    """IDs must be strings on the wire."""
    if value is None:
        return None
    return str(value)


def _work_info(employee):
    try:
        return employee.employee_work_info
    except EmployeeWorkInformation.DoesNotExist:
        return None


def build_employee_payload(employee, status: str | None = None) -> dict:
    """Build the employee payload from the HR record of truth.

    Every identifier is a string and every date is ISO-8601. Fields HR does
    not hold are null rather than guessed.
    """
    work_info = _work_info(employee)
    external_id = normalize_external_employee_id(getattr(employee, "badge_id", None))

    manager = getattr(work_info, "reporting_manager_id", None) if work_info else None
    manager_external_id = (
        normalize_external_employee_id(getattr(manager, "badge_id", None))
        if manager
        else ""
    )

    department = getattr(work_info, "department_id", None) if work_info else None
    job_position = getattr(work_info, "job_position_id", None) if work_info else None
    job_role = getattr(work_info, "job_role_id", None) if work_info else None
    company = getattr(work_info, "company_id", None) if work_info else None

    if status is None:
        status = "active" if getattr(employee, "is_active", False) else "inactive"

    return {
        "employee_id": external_id or None,
        "status": status,
        "is_active": status != "inactive",
        "first_name": _text(getattr(employee, "employee_first_name", None)),
        "last_name": _text(getattr(employee, "employee_last_name", None)),
        "full_name": _text(employee.get_full_name()),
        "email": _text(employee.get_mail()),
        "department_id": _id(getattr(department, "pk", None)),
        "department": _text(getattr(department, "department", None)),
        "job_position_id": _id(getattr(job_position, "pk", None)),
        "job_title": _text(getattr(job_position, "job_position", None)),
        "job_role_id": _id(getattr(job_role, "pk", None)),
        "job_role": _text(getattr(job_role, "job_role", None)),
        "manager_employee_id": manager_external_id or None,
        "manager_name": _text(manager.get_full_name()) if manager else None,
        "start_date": iso_date(getattr(work_info, "date_joining", None)),
        "end_date": iso_date(getattr(work_info, "contract_end_date", None)),
        "company_id": _id(getattr(company, "pk", None)),
        "company": _text(getattr(company, "company", None)),
    }


def build_envelope(
    employee,
    event_type: str,
    *,
    event_id=None,
    correlation_id: str | None = None,
    occurred_at=None,
) -> dict:
    """Build a complete, validated EventEnvelope for one employee."""
    if event_type not in HR_EVENT_TYPES:
        raise ValueError("unsupported HR event type: %s" % event_type)

    external_id = employee_external_id(employee)
    payload = build_employee_payload(
        employee,
        status="inactive"
        if event_type == EVENT_TYPE_EMPLOYEE_DEACTIVATE
        else None,
    )
    envelope = {
        "event_id": str(event_id or uuid.uuid4()),
        "source_system": SOURCE_SYSTEM,
        "event_type": event_type,
        "occurred_at": iso_timestamp(occurred_at or timezone.now()),
        "correlation_id": correlation_id
        or default_correlation_id(employee, external_id),
        "external_id": external_id,
        "payload": payload,
    }
    unexpected = set(envelope) - ENVELOPE_FIELDS
    if unexpected:  # defensive: the envelope builder must never add fields
        raise ValueError("unexpected envelope fields: %s" % sorted(unexpected))
    return envelope


def canonical_payload_hash(payload: dict) -> str:
    """Stable hash used to avoid enqueueing the same state twice."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
