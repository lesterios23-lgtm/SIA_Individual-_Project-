"""HR-side integration records.

These tables are HR's own outbox and audit trail. They are deliberately not
the gateway's ``integration_event`` or ``integration_mapping`` tables: the
gateway owns those, and HR never writes to another system's database.
"""

from __future__ import annotations

import uuid

from django.db import models


class OutboundEvent(models.Model):
    """One HR event queued for delivery to the Integration Gateway.

    ``event_id`` is also the Idempotency-Key. It is generated once and reused
    on every retry, which is what makes a replay safe.
    """

    STATUS_PENDING = "pending"
    STATUS_SENDING = "sending"
    STATUS_DELIVERED = "delivered"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_BLOCKED = "blocked"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_SENDING, "Sending"),
        (STATUS_DELIVERED, "Delivered to gateway"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
        (STATUS_BLOCKED, "Blocked by missing HR data"),
    )

    event_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, serialize=False
    )
    source_system = models.CharField(max_length=32, default="hr")
    event_type = models.CharField(max_length=64)
    correlation_id = models.CharField(max_length=128)
    external_id = models.CharField(max_length=128, blank=True)
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64, db_index=True)

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    last_http_status = models.PositiveIntegerField(null=True, blank=True)
    gateway_status = models.CharField(max_length=32, null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, null=True, blank=True)
    last_error_fields = models.JSONField(null=True, blank=True)
    response_body = models.TextField(null=True, blank=True)

    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at"],
                name="limbus_out_status_next_idx",
            ),
            models.Index(
                fields=["event_type", "external_id", "payload_hash"],
                name="limbus_out_dedupe_idx",
            ),
        ]

    def __str__(self) -> str:
        return "%s %s (%s)" % (self.event_type, self.external_id, self.status)


class OutboundEventAttempt(models.Model):
    """Audit row for one delivery attempt against the gateway."""

    OUTCOME_SENT = "sent"
    OUTCOME_RETRY = "retry"
    OUTCOME_FAILED = "failed"

    OUTCOME_CHOICES = (
        (OUTCOME_SENT, "Sent"),
        (OUTCOME_RETRY, "Scheduled for retry"),
        (OUTCOME_FAILED, "Failed permanently"),
    )

    event = models.ForeignKey(
        OutboundEvent, on_delete=models.CASCADE, related_name="attempts"
    )
    attempt_no = models.PositiveIntegerField()
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    http_status = models.PositiveIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES)
    error = models.TextField(null=True, blank=True)
    response_body = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ("attempt_no",)
        constraints = [
            models.UniqueConstraint(
                fields=["event", "attempt_no"], name="limbus_attempt_unique"
            )
        ]

    def __str__(self) -> str:
        return "%s attempt %s (%s)" % (self.event_id, self.attempt_no, self.outcome)


class InboundEvent(models.Model):
    """A Production event delivered to HR, stored idempotently.

    The gateway's delivery contract is not yet published in the OpenAPI
    document. This table is the HR-side landing zone so the adapter can be
    swapped without changing the domain handling.
    """

    STATUS_RECEIVED = "received"
    STATUS_PROCESSED = "processed"
    STATUS_EXCEPTION = "exception"
    STATUS_IGNORED = "ignored"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = (
        (STATUS_RECEIVED, "Received"),
        (STATUS_PROCESSED, "Processed"),
        (STATUS_EXCEPTION, "Needs HR follow-up"),
        (STATUS_IGNORED, "Ignored"),
        (STATUS_FAILED, "Failed"),
    )

    event_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, serialize=False
    )
    source_system = models.CharField(max_length=32)
    event_type = models.CharField(max_length=64)
    correlation_id = models.CharField(max_length=128)
    external_id = models.CharField(max_length=128)
    payload = models.JSONField()
    occurred_at = models.DateTimeField()

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_RECEIVED, db_index=True
    )
    resolution = models.CharField(max_length=64, null=True, blank=True)
    operator_external_id = models.CharField(max_length=128, null=True, blank=True)
    resolved_employee = models.ForeignKey(
        "employee.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    error = models.TextField(null=True, blank=True)

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-received_at",)

    def __str__(self) -> str:
        return "%s %s (%s)" % (self.event_type, self.external_id, self.status)
