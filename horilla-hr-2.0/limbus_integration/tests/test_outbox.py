"""Tests for outbox idempotency, retry policy and status handling."""

from __future__ import annotations

from datetime import timedelta

import requests
from django.test import TestCase, override_settings
from django.utils import timezone

from limbus_integration.client import GatewayClient
from limbus_integration.models import OutboundEvent, OutboundEventAttempt
from limbus_integration.outbox import (
    enqueue_upsert,
    event_result,
    poll_event,
    process_due_events,
    requeue_event,
)

from .base import EmployeeFixtureMixin
from .test_client import FakeResponse, FakeSession


def _client(session):
    return GatewayClient(
        base_url="http://gateway.test/api/v1/integration",
        token="test-token",
        timeout=5,
        session=session,
    )


@override_settings(LIMBUS_AUTO_PUBLISH=False)
class OutboxTests(EmployeeFixtureMixin, TestCase):
    def setUp(self):
        self.employee = self.make_operator()
        self.base = timezone.now()

    def _event(self, **kwargs):
        return enqueue_upsert(self.employee, occurred_at=self.base, **kwargs)

    def test_202_received_marks_delivered_and_records_attempt(self):
        event = self._event()
        session = FakeSession(
            [FakeResponse(202, {"event_id": str(event.event_id), "status": "received"})]
        )

        results = process_due_events(client=_client(session), now=self.base)

        event.refresh_from_db()
        self.assertEqual(len(results), 1)
        self.assertEqual(event.status, OutboundEvent.STATUS_DELIVERED)
        self.assertEqual(event.attempt_count, 1)
        self.assertEqual(event.gateway_status, "received")
        self.assertIsNotNone(event.delivered_at)
        attempt = OutboundEventAttempt.objects.get(event=event)
        self.assertEqual(attempt.outcome, OutboundEventAttempt.OUTCOME_SENT)

    def test_202_succeeded_marks_succeeded(self):
        event = self._event()
        session = FakeSession(
            [
                FakeResponse(
                    202, {"event_id": str(event.event_id), "status": "succeeded"}
                )
            ]
        )
        process_due_events(client=_client(session), now=self.base)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_SUCCEEDED)
        self.assertIsNotNone(event.processed_at)

    def test_400_fails_permanently_without_retry(self):
        event = self._event()
        session = FakeSession(
            [
                FakeResponse(
                    400,
                    {
                        "code": "invalid_payload",
                        "message": "bad field",
                        "fields": {"payload.status": "is required"},
                    },
                )
            ]
        )
        process_due_events(client=_client(session), now=self.base)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_FAILED)
        self.assertIsNone(event.next_attempt_at)
        self.assertEqual(event.last_error_code, "invalid_payload")
        self.assertEqual(
            event.last_error_fields, {"payload.status": "is required"}
        )

    def test_500_schedules_retry_and_reuses_the_idempotency_key(self):
        event = self._event()
        session = FakeSession(
            [
                FakeResponse(503, {"code": "unavailable", "message": "later"}),
                FakeResponse(
                    202, {"event_id": str(event.event_id), "status": "received"}
                ),
            ]
        )
        client = _client(session)

        process_due_events(client=client, now=self.base)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_PENDING)
        self.assertEqual(event.attempt_count, 1)
        self.assertGreaterEqual(
            event.next_attempt_at, self.base + timedelta(seconds=1)
        )
        self.assertLess(event.next_attempt_at, self.base + timedelta(seconds=2))

        process_due_events(
            client=client, now=self.base + timedelta(seconds=2)
        )
        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_DELIVERED)
        self.assertEqual(event.attempt_count, 2)

        first_key = session.posts[0][1]["headers"]["Idempotency-Key"]
        second_key = session.posts[1][1]["headers"]["Idempotency-Key"]
        self.assertEqual(first_key, second_key)
        self.assertEqual(first_key, str(event.event_id))

    @override_settings(LIMBUS_OUTBOX_MAX_ATTEMPTS=2)
    def test_max_attempts_moves_event_to_failed(self):
        event = self._event()
        session = FakeSession(
            [
                FakeResponse(503, {"code": "unavailable", "message": "later"}),
                FakeResponse(503, {"code": "unavailable", "message": "later"}),
            ]
        )
        client = _client(session)

        process_due_events(client=client, now=self.base)
        process_due_events(
            client=client, now=self.base + timedelta(seconds=2)
        )

        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_FAILED)
        self.assertEqual(event.attempt_count, 2)
        self.assertIsNone(event.next_attempt_at)

    def test_timeout_is_retryable(self):
        event = self._event()
        session = FakeSession([requests.Timeout("timed out")])
        process_due_events(client=_client(session), now=self.base)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_PENDING)
        self.assertEqual(event.last_error_code, "transport_error")

    def test_409_fails_permanently(self):
        event = self._event()
        session = FakeSession(
            [FakeResponse(409, {"code": "conflict", "message": "different payload"})]
        )
        process_due_events(client=_client(session), now=self.base)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_FAILED)
        self.assertIsNone(event.next_attempt_at)

    def test_poll_updates_delivered_event(self):
        event = self._event()
        post_session = FakeSession(
            [FakeResponse(202, {"event_id": str(event.event_id), "status": "received"})]
        )
        process_due_events(client=_client(post_session), now=self.base)

        poll_session = FakeSession(
            get_responses=[
                FakeResponse(
                    200,
                    {
                        "event_id": str(event.event_id),
                        "status": "succeeded",
                        "attempt_count": 1,
                    },
                )
            ]
        )
        result = poll_event(event.event_id, client=_client(poll_session))

        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_SUCCEEDED)
        self.assertEqual(result["status"], "succeeded")
        self.assertIsNotNone(event.processed_at)

    def test_requeue_failed_event(self):
        event = self._event()
        session = FakeSession(
            [FakeResponse(400, {"code": "invalid_payload", "message": "bad"})]
        )
        process_due_events(client=_client(session), now=self.base)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_FAILED)

        result = requeue_event(event.event_id, reset_attempts=True)
        event.refresh_from_db()
        self.assertEqual(event.status, OutboundEvent.STATUS_PENDING)
        self.assertEqual(event.attempt_count, 0)
        self.assertIsNone(event.last_error)
        self.assertEqual(result["event_id"], str(event.event_id))

    def test_result_always_contains_both_ids(self):
        event = self._event()
        result = event_result(event)
        self.assertEqual(result["event_id"], str(event.event_id))
        self.assertEqual(result["correlation_id"], event.correlation_id)
        self.assertTrue(result["event_id"])
        self.assertTrue(result["correlation_id"])
