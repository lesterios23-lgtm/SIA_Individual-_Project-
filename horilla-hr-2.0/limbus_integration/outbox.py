"""Transactional outbox for HR -> gateway delivery.

The outbox is the sender queue required by the handoff. An event is stored
before any network call, the event_id is reused as the Idempotency-Key on
every retry, and a 4xx response is never retried unchanged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from .client import GatewayClient, response_body_text
from .config import outbox_batch_size, outbox_max_attempts
from .events import (
    EVENT_TYPE_EMPLOYEE_DEACTIVATE,
    EVENT_TYPE_EMPLOYEE_UPSERT,
    HR_EVENT_TYPES,
    build_employee_payload,
    canonical_payload_hash,
    default_correlation_id,
    iso_timestamp,
    normalize_external_employee_id,
)
from .models import OutboundEvent, OutboundEventAttempt

logger = logging.getLogger(__name__)

# The handoff's retry intervals. Attempt 1 is immediate; a failure schedules
# attempt 2 after 1s, then 5s, 15s, 60s. The 300s value is the next interval
# if the attempt cap is raised above the default five.
RETRY_DELAYS_SECONDS = (1, 5, 15, 60, 300)


def retry_delay(attempt_count: int) -> float:
    index = max(0, min(attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1))
    return float(RETRY_DELAYS_SECONDS[index])


def _as_uuid(value) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def enqueue_employee_event(
    employee,
    event_type: str,
    *,
    correlation_id: str | None = None,
    occurred_at=None,
    force: bool = False,
    event_id=None,
    payload_status: str | None = None,
) -> OutboundEvent:
    """Store one HR event, or return the existing identical event.

    Identical means the same event type, external employee ID and canonical
    payload. That makes signal-driven saves safe: editing a field that does
    not change the published payload does not create a second event.
    """
    if event_type not in HR_EVENT_TYPES:
        raise ValueError("unsupported HR event type: %s" % event_type)

    payload = build_employee_payload(employee, status=payload_status)
    external_id = normalize_external_employee_id(payload.get("employee_id"))
    payload_hash = canonical_payload_hash(payload)
    event_uuid = _as_uuid(event_id) if event_id else uuid.uuid4()

    if not force:
        existing = (
            OutboundEvent.objects.filter(
                event_type=event_type,
                external_id=external_id,
                payload_hash=payload_hash,
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            return existing

    missing_identity = not external_id
    now = occurred_at or timezone.now()
    event = OutboundEvent(
        event_id=event_uuid,
        source_system="hr",
        event_type=event_type,
        correlation_id=correlation_id
        or default_correlation_id(employee, external_id),
        external_id=external_id,
        payload=payload,
        payload_hash=payload_hash,
        status=OutboundEvent.STATUS_BLOCKED
        if missing_identity
        else OutboundEvent.STATUS_PENDING,
        next_attempt_at=None if missing_identity else now,
        occurred_at=now,
        max_attempts=outbox_max_attempts(),
        last_error=(
            "employee has no external employee ID; set Employee.badge_id"
            if missing_identity
            else None
        ),
        last_error_code="missing_identity" if missing_identity else None,
    )
    event.save()
    logger.info(
        "queued HR integration event",
        extra={
            "event_id": str(event.event_id),
            "correlation_id": event.correlation_id,
            "event_type": event.event_type,
            "external_id": event.external_id,
            "status": event.status,
        },
    )
    return event


def enqueue_upsert(employee, **kwargs) -> OutboundEvent:
    return enqueue_employee_event(
        employee, EVENT_TYPE_EMPLOYEE_UPSERT, **kwargs
    )


def enqueue_deactivate(employee, **kwargs) -> OutboundEvent:
    return enqueue_employee_event(
        employee,
        EVENT_TYPE_EMPLOYEE_DEACTIVATE,
        payload_status="inactive",
        **kwargs,
    )


def envelope_from_event(event: OutboundEvent) -> dict:
    """Rebuild the exact envelope that was stored at enqueue time."""
    return {
        "event_id": str(event.event_id),
        "source_system": event.source_system,
        "event_type": event.event_type,
        "occurred_at": iso_timestamp(event.occurred_at),
        "correlation_id": event.correlation_id,
        "external_id": event.external_id,
        "payload": event.payload,
    }


def _lock_queryset(queryset):
    # SQLite (the default local database) has no SELECT ... FOR UPDATE. Postgres
    # does, and skip_locked lets several workers drain the queue in parallel.
    if connection.features.has_select_for_update:
        return queryset.select_for_update(
            skip_locked=connection.features.has_select_for_update_skip_locked
        )
    return queryset


def claim_due_events(limit: int | None = None, now=None) -> list[OutboundEvent]:
    """Move due events to ``sending`` and return them.

    Claiming increments attempt_count before the network call, so a worker
    that dies mid-request still consumes one attempt.
    """
    now = now or timezone.now()
    limit = limit or outbox_batch_size()
    due = Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)

    with transaction.atomic():
        queryset = OutboundEvent.objects.filter(
            status=OutboundEvent.STATUS_PENDING
        ).filter(due).order_by("created_at")
        queryset = _lock_queryset(queryset)
        events = list(queryset[:limit])
        for event in events:
            event.status = OutboundEvent.STATUS_SENDING
            event.attempt_count += 1
            event.last_attempt_at = now
            event.save(
                update_fields=[
                    "status",
                    "attempt_count",
                    "last_attempt_at",
                    "updated_at",
                ]
            )
    return events


def _record_attempt(
    event: OutboundEvent,
    response,
    outcome: str,
    started_at,
    finished_at,
) -> None:
    OutboundEventAttempt.objects.create(
        event=event,
        attempt_no=event.attempt_count,
        started_at=started_at,
        finished_at=finished_at,
        http_status=response.http_status,
        outcome=outcome,
        error=response.error_message or response.transport_error,
        response_body=response_body_text(response),
    )


def process_event(event: OutboundEvent, client, now=None) -> dict:
    """Send one claimed event and record the outcome.

    Returns the standard result object, which always carries both event_id and
    correlation_id.
    """
    now = now or timezone.now()
    if event.status != OutboundEvent.STATUS_SENDING:
        event.status = OutboundEvent.STATUS_SENDING
        event.attempt_count += 1
        event.last_attempt_at = now

    started_at = timezone.now()
    response = client.post_event(envelope_from_event(event))
    finished_at = timezone.now()

    event.last_http_status = response.http_status
    event.last_error = response.error_message or response.transport_error
    event.last_error_code = response.error_code
    event.last_error_fields = response.error_fields
    event.response_body = response_body_text(response)
    event.gateway_status = response.gateway_status

    if response.http_status is not None and 200 <= response.http_status < 300:
        event.delivered_at = now
        event.next_attempt_at = None
        event.last_error = None
        event.last_error_code = None
        event.last_error_fields = None
        if response.gateway_status in ("succeeded", "duplicate"):
            event.status = OutboundEvent.STATUS_SUCCEEDED
            event.processed_at = now
        else:
            # 202 received: the gateway has durably stored the event. It owns
            # the rest of the processing and will publish the result event.
            event.status = OutboundEvent.STATUS_DELIVERED
        outcome = OutboundEventAttempt.OUTCOME_SENT
    elif response.retryable:
        if event.attempt_count >= event.max_attempts:
            event.status = OutboundEvent.STATUS_FAILED
            event.next_attempt_at = None
            outcome = OutboundEventAttempt.OUTCOME_FAILED
        else:
            delay = (
                response.retry_after
                if response.retry_after is not None
                else retry_delay(event.attempt_count)
            )
            event.status = OutboundEvent.STATUS_PENDING
            event.next_attempt_at = now + timedelta(seconds=delay)
            outcome = OutboundEventAttempt.OUTCOME_RETRY
    else:
        # 400/401/403/409: retrying the same payload unchanged is forbidden.
        event.status = OutboundEvent.STATUS_FAILED
        event.next_attempt_at = None
        outcome = OutboundEventAttempt.OUTCOME_FAILED

    event.save()
    _record_attempt(event, response, outcome, started_at, finished_at)

    if event.status == OutboundEvent.STATUS_FAILED:
        logger.error(
            "HR integration event failed",
            extra={
                "event_id": str(event.event_id),
                "correlation_id": event.correlation_id,
                "event_type": event.event_type,
                "external_id": event.external_id,
                "http_status": event.last_http_status,
                "error_code": event.last_error_code,
            },
        )
    else:
        logger.info(
            "HR integration event processed",
            extra={
                "event_id": str(event.event_id),
                "correlation_id": event.correlation_id,
                "event_type": event.event_type,
                "external_id": event.external_id,
                "status": event.status,
                "http_status": event.last_http_status,
            },
        )
    return event_result(event)


def process_due_events(
    limit: int | None = None, client=None, now=None
) -> list[dict]:
    """Drain due events once. Returns one result per event."""
    client = client or GatewayClient()
    return [
        process_event(event, client, now=now)
        for event in claim_due_events(limit=limit, now=now)
    ]


def poll_event(event_id, client=None) -> dict:
    """Refresh a delivered event's status with the documented GET endpoint.

    Polling is advisory: a transient poll failure never rewrites a successful
    delivery as a failure.
    """
    client = client or GatewayClient()
    event = OutboundEvent.objects.get(event_id=_as_uuid(event_id))
    if event.status not in (
        OutboundEvent.STATUS_DELIVERED,
        OutboundEvent.STATUS_SUCCEEDED,
    ):
        return event_result(event)

    response = client.get_event(str(event.event_id))
    if response.http_status is not None and 200 <= response.http_status < 300:
        event.gateway_status = response.gateway_status
        event.last_http_status = response.http_status
        event.response_body = response_body_text(response)
        if response.gateway_status in ("succeeded", "duplicate"):
            event.status = OutboundEvent.STATUS_SUCCEEDED
            event.processed_at = event.processed_at or timezone.now()
            event.last_error = None
            event.last_error_code = None
            event.last_error_fields = None
        elif response.gateway_status == "failed":
            event.status = OutboundEvent.STATUS_FAILED
            event.last_error = (
                response.error_message or "gateway reported processing failure"
            )
            event.last_error_code = response.error_code or "gateway_failed"
            event.last_error_fields = response.error_fields
        event.save()
    else:
        event.last_http_status = response.http_status
        event.last_error = (
            response.error_message
            or response.transport_error
            or "gateway status poll failed"
        )
        event.last_error_code = response.error_code or "poll_failed"
        event.save(
            update_fields=[
                "last_http_status",
                "last_error",
                "last_error_code",
                "updated_at",
            ]
        )
    return event_result(event)


def requeue_event(event_id, *, reset_attempts=False, now=None) -> dict:
    """Put a terminal event back in the queue after an operator fix."""
    event = OutboundEvent.objects.get(event_id=_as_uuid(event_id))
    if not event.external_id:
        raise ValueError(
            "event %s has no external_id; fix Employee.badge_id and re-sync"
            % event.event_id
        )
    if event.status not in (
        OutboundEvent.STATUS_FAILED,
        OutboundEvent.STATUS_BLOCKED,
        OutboundEvent.STATUS_DELIVERED,
        OutboundEvent.STATUS_SUCCEEDED,
    ):
        raise ValueError(
            "event %s is %s and cannot be requeued" % (event.event_id, event.status)
        )
    event.status = OutboundEvent.STATUS_PENDING
    event.next_attempt_at = now or timezone.now()
    event.last_error = None
    event.last_error_code = None
    event.last_error_fields = None
    if reset_attempts:
        event.attempt_count = 0
    event.save()
    return event_result(event)


def reclaim_stale_sending(*, older_than_seconds=600, now=None) -> int:
    """Return events abandoned by a crashed worker to the queue."""
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=older_than_seconds)
    stale = Q(last_attempt_at__lt=cutoff) | Q(last_attempt_at__isnull=True)
    return OutboundEvent.objects.filter(
        status=OutboundEvent.STATUS_SENDING
    ).filter(stale).update(
        status=OutboundEvent.STATUS_PENDING,
        next_attempt_at=now,
        last_error="worker interrupted; event reclaimed",
        last_error_code="worker_reclaimed",
        updated_at=now,
    )


def event_result(event: OutboundEvent, *, include_payload=False) -> dict:
    """The standard result shape returned by every HR integration operation."""
    result = {
        "event_id": str(event.event_id),
        "correlation_id": event.correlation_id,
        "external_id": event.external_id,
        "event_type": event.event_type,
        "status": event.status,
        "attempt_count": event.attempt_count,
        "max_attempts": event.max_attempts,
        "gateway_status": event.gateway_status,
        "http_status": event.last_http_status,
        "error_code": event.last_error_code,
        "error": event.last_error,
        "occurred_at": iso_timestamp(event.occurred_at),
        "next_attempt_at": iso_timestamp(event.next_attempt_at),
        "delivered_at": iso_timestamp(event.delivered_at),
        "processed_at": iso_timestamp(event.processed_at),
    }
    if include_payload:
        result["payload"] = event.payload
    return result
