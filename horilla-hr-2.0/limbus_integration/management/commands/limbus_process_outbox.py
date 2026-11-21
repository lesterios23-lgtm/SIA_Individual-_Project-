"""Deliver due HR outbox events to the Integration Gateway."""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from limbus_integration.config import IntegrationConfigurationError
from limbus_integration.outbox import (
    process_due_events,
    reclaim_stale_sending,
)

from ._util import write_json


class Command(BaseCommand):
    help = (
        "Send pending HR events to the Integration Gateway. Retries use the "
        "same event_id/Idempotency-Key; 4xx responses are not retried."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of events to process in this run.",
        )
        parser.add_argument(
            "--reclaim-stale",
            action="store_true",
            help="Return events abandoned by a crashed worker to the queue first.",
        )
        parser.add_argument(
            "--stale-seconds",
            type=int,
            default=600,
            help="Age in seconds after which a 'sending' event is reclaimed.",
        )

    def handle(self, *args, **options):
        run_correlation_id = "limbus-outbox-%s" % uuid.uuid4()
        try:
            if options["reclaim_stale"]:
                reclaimed = reclaim_stale_sending(
                    older_than_seconds=options["stale_seconds"]
                )
                write_json(
                    self,
                    {
                        "event_id": None,
                        "correlation_id": run_correlation_id,
                        "status": "reclaimed",
                        "count": reclaimed,
                    },
                )

            results = process_due_events(limit=options["limit"])
        except IntegrationConfigurationError as exc:
            write_json(
                self,
                {
                    "event_id": None,
                    "correlation_id": run_correlation_id,
                    "status": "error",
                    "error": str(exc),
                },
            )
            raise CommandError(str(exc)) from exc

        for result in results:
            write_json(self, result)

        if not results:
            write_json(
                self,
                {
                    "event_id": None,
                    "correlation_id": run_correlation_id,
                    "status": "idle",
                    "count": 0,
                },
            )

        if any(result["status"] == "failed" for result in results):
            raise CommandError(
                "one or more events failed permanently; inspect the result rows"
            )
