"""Queue an employee.deactivate event for one employee."""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from limbus_integration.events import (
    EVENT_TYPE_EMPLOYEE_DEACTIVATE,
    default_correlation_id,
)
from limbus_integration.outbox import enqueue_deactivate, event_result

from ._util import resolve_employee, write_json


class Command(BaseCommand):
    help = (
        "Publish an employee.deactivate event. HR remains the authority for "
        "the local is_active value; use --force only when the local "
        "deactivation is handled by another HR process."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--employee",
            required=True,
            help="External employee ID (badge_id) or local PK.",
        )
        parser.add_argument(
            "--correlation-id",
            default=None,
            help="Override the default hr-employee-<id> correlation ID.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Queue the event even when the employee is still active in HR.",
        )

    def handle(self, *args, **options):
        employee = resolve_employee(options["employee"])
        if employee is None:
            write_json(
                self,
                {
                    "event_id": None,
                    "correlation_id": "limbus-deactivate-%s" % uuid.uuid4(),
                    "external_id": str(options["employee"]),
                    "event_type": EVENT_TYPE_EMPLOYEE_DEACTIVATE,
                    "status": "not_found",
                    "error": "no employee matches this ID or PK",
                },
            )
            raise CommandError("employee not found")

        if employee.is_active and not options["force"]:
            write_json(
                self,
                {
                    "event_id": None,
                    "correlation_id": options["correlation_id"]
                    or default_correlation_id(employee),
                    "external_id": employee.badge_id or "",
                    "event_type": EVENT_TYPE_EMPLOYEE_DEACTIVATE,
                    "status": "refused",
                    "error": (
                        "employee is still active in HR; deactivate locally "
                        "first or pass --force"
                    ),
                },
            )
            raise CommandError("employee is still active")

        event = enqueue_deactivate(
            employee, correlation_id=options["correlation_id"]
        )
        write_json(self, event_result(event))
