"""Shared helpers for the Limbus management commands."""

from __future__ import annotations

import json

from employee.models import Employee

from limbus_integration.events import normalize_external_employee_id


def write_json(command, payload: dict) -> None:
    command.stdout.write(json.dumps(payload, default=str, sort_keys=True))


def resolve_employee(value):
    """Resolve an employee by external ID (badge_id) or local primary key."""
    text = str(value).strip()
    if not text:
        return None

    employee = Employee.objects.filter(badge_id=text).first()
    if employee is not None:
        return employee
    employee = Employee.objects.filter(badge_id__iexact=text).first()
    if employee is not None:
        return employee

    if text.isdigit():
        employee = Employee.objects.filter(pk=int(text)).first()
        if employee is not None:
            return employee

    normalized = normalize_external_employee_id(text)
    if normalized:
        for candidate in Employee.objects.exclude(badge_id__isnull=True).only(
            "id", "badge_id"
        ):
            if normalize_external_employee_id(candidate.badge_id) == normalized:
                return Employee.objects.filter(pk=candidate.pk).first()
    return None
