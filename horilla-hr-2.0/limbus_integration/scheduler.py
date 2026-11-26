"""
scheduler.py

Registers the periodic outbox worker that delivers queued HR lifecycle events
(hr.employee.upsert / hr.employee.deactivate) to the Core ERP Integration Gateway.
"""

import logging

from django.conf import settings

from horilla.scheduling import register_job

logger = logging.getLogger(__name__)


def process_limbus_outbox():
    """
    Drain due HR integration outbox events to the Core ERP Gateway.
    Skips quietly when LIMBUS_HR_TOKEN is not configured.
    """
    token = (getattr(settings, "LIMBUS_HR_TOKEN", "") or "").strip()
    if not token:
        return

    from limbus_integration.outbox import process_due_events, reclaim_stale_sending

    reclaim_stale_sending()
    results = process_due_events()
    if results:
        logger.info(
            "Processed %d HR integration outbox event(s).",
            len(results),
        )


register_job(process_limbus_outbox, "interval", seconds=30)
