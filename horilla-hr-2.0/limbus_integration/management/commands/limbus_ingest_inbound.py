"""Ingest Production events delivered to HR.

The gateway's inbound delivery mechanism is not yet documented. Until it is,
this command is the adapter: it accepts a JSON object, a JSON array, or
newline-delimited JSON from a file or stdin. The envelope is the same
documented EventEnvelope used outbound.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from limbus_integration.inbound import ingest_inbound_event

from ._util import write_json


def _load_envelopes(text: str) -> list:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return [
            json.loads(line) for line in stripped.splitlines() if line.strip()
        ]
    if isinstance(data, list):
        return data
    return [data]


class Command(BaseCommand):
    help = "Ingest Production event envelopes and resolve the accountable operator."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="Path to a JSON/NDJSON file, or - to read stdin.",
        )

    def handle(self, *args, **options):
        source = options["file"]
        try:
            if source == "-":
                text = sys.stdin.read()
            else:
                text = Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            write_json(
                self,
                {
                    "event_id": None,
                    "correlation_id": "limbus-inbound-%s" % uuid.uuid4(),
                    "status": "error",
                    "error": str(exc),
                },
            )
            raise CommandError(str(exc)) from exc

        try:
            envelopes = _load_envelopes(text)
        except json.JSONDecodeError as exc:
            write_json(
                self,
                {
                    "event_id": None,
                    "correlation_id": "limbus-inbound-%s" % uuid.uuid4(),
                    "status": "error",
                    "error": "invalid JSON: %s" % exc,
                },
            )
            raise CommandError("invalid JSON") from exc

        failed = False
        for envelope in envelopes:
            result = ingest_inbound_event(envelope)
            write_json(self, result)
            if result["status"] in ("rejected", "failed"):
                failed = True

        if not envelopes:
            write_json(
                self,
                {
                    "event_id": None,
                    "correlation_id": "limbus-inbound-%s" % uuid.uuid4(),
                    "status": "idle",
                    "count": 0,
                },
            )

        if failed:
            raise CommandError("one or more inbound events were rejected")
