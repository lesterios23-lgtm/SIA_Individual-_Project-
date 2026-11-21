"""Tests for the HR payload and envelope builders."""

from __future__ import annotations

from datetime import date

from django.test import TestCase, override_settings

from employee.models import Employee
from horilla.testkit import make_employee
from limbus_integration.events import (
    EVENT_TYPE_EMPLOYEE_DEACTIVATE,
    EVENT_TYPE_EMPLOYEE_UPSERT,
    MissingEmployeeIdentity,
    build_employee_payload,
    build_envelope,
    canonical_payload_hash,
    employee_external_id,
    normalize_external_employee_id,
)
from limbus_integration.models import OutboundEvent
from limbus_integration.outbox import enqueue_deactivate, enqueue_upsert

from .base import EmployeeFixtureMixin


@override_settings(LIMBUS_AUTO_PUBLISH=False)
class PayloadTests(EmployeeFixtureMixin, TestCase):
    def test_external_id_normalization_preserves_case(self):
        self.assertEqual(
            normalize_external_employee_id("  emp   001  "), "emp 001"
        )
        self.assertEqual(normalize_external_employee_id(None), "")
        self.assertEqual(normalize_external_employee_id("   "), "")

    def test_payload_uses_strings_and_iso_dates(self):
        employee = self.make_operator()
        payload = build_employee_payload(employee)

        self.assertEqual(payload["employee_id"], "EMP-001")
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["department_id"], str(self.department.pk))
        self.assertEqual(payload["department"], "Manufacturing")
        self.assertEqual(payload["job_position_id"], str(self.job_position.pk))
        self.assertEqual(payload["job_title"], "Machine Operator")
        self.assertEqual(payload["manager_employee_id"], "EMP-000")
        self.assertEqual(payload["start_date"], "2025-01-06")
        self.assertEqual(payload["end_date"], "2026-01-05")
        self.assertEqual(payload["company_id"], str(self.company.pk))
        self.assertIsInstance(payload["employee_id"], str)
        self.assertIsInstance(payload["department_id"], str)

    def test_payload_status_can_be_forced_to_inactive(self):
        employee = self.make_operator()
        payload = build_employee_payload(employee, status="inactive")
        self.assertEqual(payload["status"], "inactive")

    def test_missing_badge_id_raises(self):
        employee = make_employee(
            company=self.company, email="nobadge@test.horilla"
        )
        with self.assertRaises(MissingEmployeeIdentity):
            employee_external_id(employee)

    def test_envelope_has_only_documented_fields(self):
        employee = self.make_operator()
        envelope = build_envelope(employee, EVENT_TYPE_EMPLOYEE_UPSERT)
        self.assertEqual(
            set(envelope),
            {
                "event_id",
                "source_system",
                "event_type",
                "occurred_at",
                "correlation_id",
                "external_id",
                "payload",
            },
        )
        self.assertEqual(envelope["source_system"], "hr")
        self.assertEqual(envelope["event_type"], "employee.upsert")
        self.assertEqual(envelope["correlation_id"], "hr-employee-EMP-001")
        self.assertEqual(envelope["external_id"], "EMP-001")

    def test_payload_hash_is_order_independent(self):
        self.assertEqual(
            canonical_payload_hash({"a": "1", "b": "2"}),
            canonical_payload_hash({"b": "2", "a": "1"}),
        )


@override_settings(LIMBUS_AUTO_PUBLISH=False)
class EnqueueTests(EmployeeFixtureMixin, TestCase):
    def test_upsert_is_idempotent_for_identical_payload(self):
        employee = self.make_operator()
        first = enqueue_upsert(employee)
        second = enqueue_upsert(employee)
        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual(OutboundEvent.objects.count(), 1)

    def test_changed_payload_creates_a_new_event(self):
        employee = self.make_operator()
        first = enqueue_upsert(employee)

        employee.employee_first_name = "Renamed"
        employee.save()
        second = enqueue_upsert(employee)

        self.assertNotEqual(first.event_id, second.event_id)
        self.assertEqual(OutboundEvent.objects.count(), 2)

    def test_deactivate_event_forces_inactive_payload(self):
        employee = self.make_operator()
        event = enqueue_deactivate(employee)
        self.assertEqual(event.event_type, EVENT_TYPE_EMPLOYEE_DEACTIVATE)
        self.assertEqual(event.payload["status"], "inactive")
        self.assertEqual(event.status, OutboundEvent.STATUS_PENDING)

    def test_missing_identity_is_blocked_not_invented(self):
        employee = make_employee(
            company=self.company, email="blocked@test.horilla"
        )
        event = enqueue_upsert(employee)
        self.assertEqual(event.status, OutboundEvent.STATUS_BLOCKED)
        self.assertEqual(event.external_id, "")
        self.assertEqual(event.last_error_code, "missing_identity")
        self.assertTrue(event.correlation_id.startswith("hr-employee-pk-"))
        self.assertIsNotNone(event.event_id)

    def test_force_creates_a_second_event(self):
        employee = self.make_operator()
        first = enqueue_upsert(employee)
        second = enqueue_upsert(employee, force=True)
        self.assertNotEqual(first.event_id, second.event_id)


@override_settings(LIMBUS_AUTO_PUBLISH=True)
class LifecycleSignalTests(EmployeeFixtureMixin, TestCase):
    def setUp(self):
        OutboundEvent.objects.all().delete()

    def test_creating_an_employee_queues_an_upsert(self):
        employee = self.make_operator(badge="EMP-100", email="new@test.horilla")
        self.assertTrue(
            OutboundEvent.objects.filter(
                event_type=EVENT_TYPE_EMPLOYEE_UPSERT,
                external_id="EMP-100",
            ).exists()
        )
        self.assertIsNotNone(employee.pk)

    def test_active_to_inactive_queues_deactivate(self):
        employee = self.make_operator(badge="EMP-101", email="leaver@test.horilla")
        OutboundEvent.objects.all().delete()

        employee.is_active = False
        employee.save()

        event = OutboundEvent.objects.get(external_id="EMP-101")
        self.assertEqual(event.event_type, EVENT_TYPE_EMPLOYEE_DEACTIVATE)
        self.assertEqual(event.payload["status"], "inactive")

    def test_inactive_to_active_queues_upsert(self):
        employee = self.make_operator(
            badge="EMP-102", email="returner@test.horilla", active=False
        )
        OutboundEvent.objects.all().delete()

        employee.is_active = True
        employee.save()

        event = OutboundEvent.objects.get(external_id="EMP-102")
        self.assertEqual(event.event_type, EVENT_TYPE_EMPLOYEE_UPSERT)
        self.assertEqual(event.payload["status"], "active")

    def test_work_information_change_queues_upsert(self):
        employee = self.make_operator(badge="EMP-103", email="move@test.horilla")
        OutboundEvent.objects.all().delete()

        work_info = employee.employee_work_info
        work_info.date_joining = date(2025, 2, 1)
        work_info.save()

        event = OutboundEvent.objects.get(external_id="EMP-103")
        self.assertEqual(event.event_type, EVENT_TYPE_EMPLOYEE_UPSERT)
        self.assertEqual(event.payload["start_date"], "2025-02-01")
