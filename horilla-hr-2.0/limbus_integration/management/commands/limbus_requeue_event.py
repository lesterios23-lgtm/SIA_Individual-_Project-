"""Return a terminal HR event to the outbox after an operator fix."""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from limbus_integration.models import OutboundEvent
from limbus_integration.outbox import requeue_event

from ._util import write_json


class Command(BaseCommand):
    help = "Requeue a failed or delivered HR event for another gateway attempt."

    def add_arguments(self, parser):
        parser.add_argument("--event-id", required=True, help="Event UUID.")
        parser.add_argument(
            "--reset-attempts",
            action="store_true",
            help="Reset attempt_count to zero as well as the status.",
        )

    def handle(self, *args, **options):
        correlation_id = "limbus-requeue-%s" % uuid.uuid4()
        try:
            result = requeue_event(
                options["event_id"], reset_attempts=options["reset_attempts"]
            )
        except (OutboundEvent.DoesNotExist, ValueError) as exc:
            write_json(
                self,
                {
                    "event_id": str(options["event_id"]),
                    "correlation_id": correlation_id,
                    "status": "error",
                    "error": str(exc),
                },
            )
            raise CommandError(str(exc)) from exc

        write_json(self, result)
