"""Tests for the operator-facing management commands."""

from __future__ import annotations

import json
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from limbus_integration.client import GatewayClient
from limbus_integration.models import OutboundEvent
from limbus_integration.outbox import enqueue_upsert

from .base import EmployeeFixtureMixin
from .test_client import FakeResponse, FakeSession


def _last_json(output: StringIO) -> dict:
    lines = [line for line in output.getvalue().splitlines() if line.strip()]
    return json.loads(lines[-1])


@override_settings(LIMBUS_AUTO_PUBLISH=False)
class CommandTests(EmployeeFixtureMixin, TestCase):
    def test_sync_dry_run_reports_correlation_and_no_event_id(self):
        self.make_operator()
        output = StringIO()

        call_command(
            "limbus_sync_employees",
            "--employee",
            "EMP-001",
            "--dry-run",
            stdout=output,
        )

        result = _last_json(output)
        self.assertIsNone(result["event_id"])
        self.assertEqual(result["correlation_id"], "hr-employee-EMP-001")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["payload"]["employee_id"], "EMP-001")

    def test_deactivate_refuses_an_active_employee_without_force(self):
        self.make_operator()
        output = StringIO()

        with self.assertRaises(CommandError):
            call_command(
                "limbus_deactivate_employee",
                "--employee",
                "EMP-001",
                stdout=output,
            )

        result = _last_json(output)
        self.assertIsNone(result["event_id"])
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["correlation_id"], "hr-employee-EMP-001")

    def test_deactivate_with_force_queues_the_event(self):
        self.make_operator()
        output = StringIO()

        call_command(
            "limbus_deactivate_employee",
            "--employee",
            "EMP-001",
            "--force",
            stdout=output,
        )

        result = _last_json(output)
        self.assertTrue(result["event_id"])
        self.assertEqual(result["event_type"], "employee.deactivate")
        self.assertEqual(result["correlation_id"], "hr-employee-EMP-001")

    def test_process_outbox_prints_a_result_per_event(self):
        employee = self.make_operator()
        event = enqueue_upsert(employee)
        session = FakeSession(
            [FakeResponse(202, {"event_id": str(event.event_id), "status": "received"})]
        )
        client = GatewayClient(
            base_url="http://gateway.test/api/v1/integration",
            token="test-token",
            timeout=5,
            session=session,
        )
        output = StringIO()

        with patch("limbus_integration.outbox.GatewayClient", return_value=client):
            call_command("limbus_process_outbox", stdout=output)

        result = _last_json(output)
        self.assertEqual(result["event_id"], str(event.event_id))
        self.assertEqual(result["correlation_id"], event.correlation_id)
        self.assertEqual(result["status"], "delivered")

    @override_settings(LIMBUS_HR_TOKEN="")
    def test_missing_token_refuses_to_send(self):
        employee = self.make_operator()
        enqueue_upsert(employee)
        output = StringIO()

        with self.assertRaises(CommandError):
            call_command("limbus_process_outbox", stdout=output)

        result = _last_json(output)
        self.assertIsNone(result["event_id"])
        self.assertTrue(result["correlation_id"])
        self.assertEqual(result["status"], "error")
        self.assertIn("LIMBUS_HR_TOKEN", result["error"])

    def test_event_status_command_reports_both_ids(self):
        employee = self.make_operator()
        event = enqueue_upsert(employee)
        output = StringIO()

        call_command(
            "limbus_event_status",
            "--event-id",
            str(event.event_id),
            stdout=output,
        )

        result = _last_json(output)
        self.assertEqual(result["event_id"], str(event.event_id))
        self.assertEqual(result["correlation_id"], event.correlation_id)
        self.assertEqual(result["status"], OutboundEvent.STATUS_PENDING)

    def test_ingest_inbound_command_reads_a_file(self):
        self.make_operator()
        envelope = {
            "event_id": str(uuid.uuid4()),
            "source_system": "production",
            "event_type": "build.completed",
            "occurred_at": "2026-11-20T10:30:00Z",
            "correlation_id": "build-2026-0048",
            "external_id": "BUILD-2026-0048",
            "payload": {"operator_external_id": "EMP-001"},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            output = StringIO()
            call_command(
                "limbus_ingest_inbound", "--file", str(path), stdout=output
            )

        result = _last_json(output)
        self.assertEqual(result["event_id"], envelope["event_id"])
        self.assertEqual(result["correlation_id"], "build-2026-0048")
        self.assertEqual(result["status"], "processed")
