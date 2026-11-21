"""Reconcile HR employees into the gateway outbox.

This is the recovery path for bulk changes and for records whose save
bypassed Django signals (for example a queryset .update()).
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from employee.models import Employee
from limbus_integration.events import (
    EVENT_TYPE_EMPLOYEE_UPSERT,
    MissingEmployeeIdentity,
    build_employee_payload,
    default_correlation_id,
    employee_external_id,
)
from limbus_integration.outbox import enqueue_upsert, event_result

from ._util import resolve_employee, write_json


class Command(BaseCommand):
    help = "Queue employee.upsert events for existing HR employees."

    def add_arguments(self, parser):
        parser.add_argument(
            "--employee",
            action="append",
            default=None,
            help="External employee ID (badge_id) or local PK. Repeatable.",
        )
        parser.add_argument("--company-id", default=None, help="Limit to a company.")
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include inactive employees (published with status=inactive).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and preview; do not write an outbox event.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Queue even when an identical event already exists.",
        )
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **options):
        if options["employee"]:
            employees = []
            for value in options["employee"]:
                employee = resolve_employee(value)
                if employee is None:
                    write_json(
                        self,
                        {
                            "event_id": None,
                            "correlation_id": "limbus-sync-%s" % uuid.uuid4(),
                            "external_id": str(value),
                            "event_type": EVENT_TYPE_EMPLOYEE_UPSERT,
                            "status": "not_found",
                            "error": "no employee matches this ID or PK",
                        },
                    )
                    raise CommandError("employee %s not found" % value)
                employees.append(employee)
        else:
            queryset = Employee.objects.select_related(
                "employee_work_info",
                "employee_work_info__department_id",
                "employee_work_info__job_position_id",
                "employee_work_info__job_role_id",
                "employee_work_info__reporting_manager_id",
                "employee_work_info__company_id",
            ).order_by("pk")
            if not options["include_inactive"]:
                queryset = queryset.filter(is_active=True)
            if options["company_id"]:
                queryset = queryset.filter(
                    employee_work_info__company_id=options["company_id"]
                )
            if options["limit"]:
                queryset = queryset[: options["limit"]]
            employees = list(queryset)

        if not employees:
            write_json(
                self,
                {
                    "event_id": None,
                    "correlation_id": "limbus-sync-%s" % uuid.uuid4(),
                    "status": "idle",
                    "count": 0,
                },
            )
            return

        for employee in employees:
            if options["dry_run"]:
                write_json(self, self._preview(employee))
            else:
                write_json(
                    self,
                    event_result(
                        enqueue_upsert(employee, force=options["force"])
                    ),
                )

    def _preview(self, employee) -> dict:
        try:
            external_id = employee_external_id(employee)
            payload = build_employee_payload(employee)
            return {
                "event_id": None,
                "correlation_id": default_correlation_id(employee, external_id),
                "external_id": external_id,
                "event_type": EVENT_TYPE_EMPLOYEE_UPSERT,
                "status": "dry_run",
                "error": None,
                "payload": payload,
            }
        except (MissingEmployeeIdentity, ValueError) as exc:
            return {
                "event_id": None,
                "correlation_id": default_correlation_id(employee, ""),
                "external_id": "",
                "event_type": EVENT_TYPE_EMPLOYEE_UPSERT,
                "status": "blocked",
                "error": str(exc),
            }
