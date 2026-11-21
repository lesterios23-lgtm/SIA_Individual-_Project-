"""Tests for inbound Production event handling."""

from __future__ import annotations

import uuid

from django.test import TestCase, override_settings

from limbus_integration.inbound import (
    InboundValidationError,
    ingest_inbound_event,
    validate_envelope,
)
from limbus_integration.models import InboundEvent

from .base import EmployeeFixtureMixin


@override_settings(LIMBUS_AUTO_PUBLISH=False)
class InboundTests(EmployeeFixtureMixin, TestCase):
    def envelope(self, **overrides):
        data = {
            "event_id": str(uuid.uuid4()),
            "source_system": "production",
            "event_type": "build.completed",
            "occurred_at": "2026-11-20T10:30:00Z",
            "correlation_id": "build-2026-0048",
            "external_id": "BUILD-2026-0048",
            "payload": {"operator_external_id": "EMP-001", "quantity": "10"},
        }
        data.update(overrides)
        return data

    def test_valid_event_resolves_the_operator(self):
        operator = self.make_operator()
        result = ingest_inbound_event(self.envelope())

        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["resolution"], "processed")
        self.assertEqual(result["resolved_employee_id"], operator.pk)
        self.assertEqual(result["operator_external_id"], "EMP-001")
        self.assertTrue(result["event_id"])
        self.assertEqual(result["correlation_id"], "build-2026-0048")

    def test_duplicate_event_replay_returns_original_and_creates_no_row(self):
        self.make_operator()
        data = self.envelope()

        first = ingest_inbound_event(data)
        second = ingest_inbound_event(data)

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(InboundEvent.objects.count(), 1)

    def test_missing_operator_is_an_hr_exception(self):
        result = ingest_inbound_event(self.envelope(payload={}))
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["resolution"], "missing_identity")

    def test_unknown_operator_is_an_hr_exception(self):
        result = ingest_inbound_event(
            self.envelope(payload={"operator_external_id": "EMP-999"})
        )
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["resolution"], "unknown_operator")

    def test_inactive_operator_is_an_hr_exception(self):
        self.make_operator(active=False)
        result = ingest_inbound_event(self.envelope())
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["resolution"], "inactive_operator")

    def test_rejected_time_is_an_hr_exception(self):
        self.make_operator()
        result = ingest_inbound_event(
            self.envelope(event_type="employee.rejected-time")
        )
        self.assertEqual(result["status"], "exception")
        self.assertEqual(result["resolution"], "rejected_time")

    def test_unexpected_source_is_ignored(self):
        result = ingest_inbound_event(self.envelope(source_system="hr"))
        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["resolution"], "unexpected_source")

    def test_unsupported_event_type_is_ignored(self):
        self.make_operator()
        result = ingest_inbound_event(self.envelope(event_type="part.created"))
        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["resolution"], "unsupported_event_type")

    def test_invalid_envelope_is_rejected_with_field_errors(self):
        data = self.envelope()
        del data["payload"]
        result = ingest_inbound_event(data)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["resolution"], "validation_error")
        self.assertIn("payload", result["fields"])

    def test_unknown_envelope_field_is_rejected(self):
        data = self.envelope()
        data["unexpected"] = "nope"
        with self.assertRaises(InboundValidationError) as raised:
            validate_envelope(data)
        self.assertIn("envelope", raised.exception.fields)

    def test_naive_timestamp_is_rejected(self):
        data = self.envelope(occurred_at="2026-11-20T10:30:00")
        result = ingest_inbound_event(data)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("occurred_at", result["fields"])
