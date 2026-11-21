"""Read or refresh the gateway status of one or more HR events."""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError

from limbus_integration.config import IntegrationConfigurationError
from limbus_integration.models import OutboundEvent
from limbus_integration.outbox import event_result, poll_event

from ._util import write_json


class Command(BaseCommand):
    help = "Show a queued/sent event's status, optionally polling the gateway."

    def add_arguments(self, parser):
        parser.add_argument(
            "--event-id",
            action="append",
            required=True,
            help="Event UUID. Repeat for more than one event.",
        )
        parser.add_argument(
            "--poll",
            action="store_true",
            help="Call the documented GET /events/{event_id} endpoint.",
        )

    def handle(self, *args, **options):
        exit_error = False
        for raw_event_id in options["event_id"]:
            try:
                event_uuid = uuid.UUID(str(raw_event_id))
            except (TypeError, ValueError, AttributeError):
                write_json(
                    self,
                    {
                        "event_id": str(raw_event_id),
                        "correlation_id": "limbus-status-%s" % uuid.uuid4(),
                        "status": "invalid_event_id",
                        "error": "event ID must be a UUID",
                    },
                )
                exit_error = True
                continue

            try:
                if options["poll"]:
                    result = poll_event(event_uuid)
                else:
                    event = OutboundEvent.objects.get(event_id=event_uuid)
                    result = event_result(event)
            except OutboundEvent.DoesNotExist:
                write_json(
                    self,
                    {
                        "event_id": str(event_uuid),
                        "correlation_id": "limbus-status-%s" % uuid.uuid4(),
                        "status": "not_found",
                        "error": "no HR event with this event_id",
                    },
                )
                exit_error = True
                continue
            except IntegrationConfigurationError as exc:
                write_json(
                    self,
                    {
                        "event_id": str(event_uuid),
                        "correlation_id": "limbus-status-%s" % uuid.uuid4(),
                        "status": "error",
                        "error": str(exc),
                    },
                )
                exit_error = True
                continue

            write_json(self, result)

        if exit_error:
            raise CommandError("one or more event lookups failed")
