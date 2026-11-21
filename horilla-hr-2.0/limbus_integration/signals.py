"""Keep the HR outbox in step with the employee record.

Signals only write HR's own outbox row. They never call the network, so a
gateway outage cannot make an HR save fail. Delivery is a separate worker.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from employee.models import Employee, EmployeeWorkInformation

from .config import auto_publish_enabled
from .outbox import enqueue_deactivate, enqueue_upsert

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Employee)
def capture_previous_active_state(sender, instance, **kwargs):
    """Remember the previous is_active value so a transition is detectable."""
    if instance.pk is None:
        instance._limbus_previous_is_active = None
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "is_active" not in update_fields:
        # This save cannot change the lifecycle state.
        instance._limbus_previous_is_active = instance.is_active
        return
    try:
        instance._limbus_previous_is_active = (
            Employee.objects.filter(pk=instance.pk)
            .values_list("is_active", flat=True)
            .first()
        )
    except Exception:
        # Never let integration bookkeeping break an employee save.
        instance._limbus_previous_is_active = None
        logger.exception(
            "could not read previous employee state",
            extra={"employee_pk": instance.pk},
        )


@receiver(post_save, sender=Employee)
def enqueue_employee_lifecycle(sender, instance, created=False, raw=False, **kwargs):
    if raw or not auto_publish_enabled():
        return
    try:
        previous = getattr(instance, "_limbus_previous_is_active", None)
        if previous is True and instance.is_active is False:
            enqueue_deactivate(instance)
        else:
            enqueue_upsert(instance)
    except Exception:
        logger.exception(
            "could not enqueue employee lifecycle event",
            extra={"employee_pk": instance.pk},
        )


@receiver(post_save, sender=EmployeeWorkInformation)
def enqueue_work_information_change(sender, instance, created=False, raw=False, **kwargs):
    if raw or not auto_publish_enabled():
        return
    employee = instance.employee_id
    if employee is None:
        return
    try:
        enqueue_upsert(employee)
    except Exception:
        logger.exception(
            "could not enqueue employee work-information event",
            extra={"employee_pk": getattr(employee, "pk", None)},
        )


@receiver(post_delete, sender=Employee)
def enqueue_employee_deletion(sender, instance, **kwargs):
    """A deleted HR record is a deactivation for downstream identity."""
    if not auto_publish_enabled():
        return
    try:
        enqueue_deactivate(instance)
    except Exception:
        logger.exception(
            "could not enqueue employee deletion event",
            extra={"employee_pk": instance.pk},
        )
