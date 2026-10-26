"""Tests for asset scheduled jobs."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from asset.scheduler import notify_overdue_assignments


class OverdueAssignmentNotificationTests(SimpleTestCase):
    def test_notifies_employee_for_an_overdue_unreturned_assignment(self):
        today = date(2026, 10, 26)
        bot = object()
        recipient = object()
        assignment = SimpleNamespace(
            assigned_to_employee_id=SimpleNamespace(employee_user_id=recipient),
            asset_id=SimpleNamespace(asset_name="Laptop"),
        )

        with (
            patch(
                "asset.models.AssetAssignment.objects.filter"
            ) as assignment_filter,
            patch("horilla_auth.models.HorillaUser.objects.filter") as user_filter,
            patch("asset.scheduler.notify.send") as send_notification,
            patch("asset.scheduler.date") as scheduler_date,
        ):
            assignment_filter.return_value.select_related.return_value = [assignment]
            user_filter.return_value.only.return_value.first.return_value = bot
            scheduler_date.today.return_value = today

            notify_overdue_assignments()

        assignment_filter.assert_called_once_with(
            due_date__isnull=False,
            due_date__lt=today,
            return_date__isnull=True,
        )
        assignment_filter.return_value.select_related.assert_called_once_with(
            "asset_id", "assigned_to_employee_id__employee_user_id"
        )
        send_notification.assert_called_once()
        args, kwargs = send_notification.call_args
        self.assertEqual(args, (bot,))
        self.assertIs(kwargs["recipient"], recipient)
        self.assertEqual(
            kwargs["verb"], "The asset '%(asset_name)s' is overdue for return"
        )
        self.assertEqual(kwargs["verb_params"], {"asset_name": "Laptop"})

    def test_does_not_notify_when_the_system_bot_is_missing(self):
        with (
            patch("horilla_auth.models.HorillaUser.objects.filter") as user_filter,
            patch("asset.scheduler.notify.send") as send_notification,
        ):
            user_filter.return_value.only.return_value.first.return_value = None

            notify_overdue_assignments()

        send_notification.assert_not_called()
