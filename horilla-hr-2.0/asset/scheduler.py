"""
scheduler.py

This module is used to register scheduled tasks
"""

import logging
from datetime import date, timedelta

from django.urls import reverse
from django.utils.translation import gettext_noop

from horilla.scheduling import register_job
from notifications.signals import notify

logger = logging.getLogger(__name__)


def notify_expiring_assets():
    """
    Finds all Expiring Assets and send a notification on the notify_before date.
    """
    from asset.models import Asset
    from horilla_auth.models import HorillaUser

    today = date.today()
    assets = Asset.objects.all()

    # Cache bot & superuser once
    bot = HorillaUser.objects.filter(username="Horilla Bot").only("id").first()
    superuser = HorillaUser.objects.filter(is_superuser=True).only("id").first()

    # Query only assets that are expiring today
    assets = Asset.objects.filter(
        expiry_date__isnull=False,
        expiry_date__gte=today,
    )

    for asset in assets:
        if asset.expiry_date:
            expiry_date = asset.expiry_date
            notify_date = expiry_date - timedelta(days=asset.notify_before)
            recipient = getattr(asset.owner, "employee_user_id", None) or superuser
            if notify_date == today and recipient:
                notify.send(
                    bot,
                    recipient=recipient,
                    verb=gettext_noop(
                        "The Asset '%(asset_name)s' expires in %(notify_before)s days"
                    ),
                    verb_params={
                        "asset_name": str(asset.asset_name),
                        "notify_before": str(asset.notify_before),
                    },
                    redirect=reverse("asset-category-view"),
                    label="System",
                    icon="information",
                )


def mark_expired_assets():
    """
    Finds all assets past their expiry date and sets their status to Not-Available.
    """
    from asset.models import Asset

    today = date.today()
    expired = Asset.objects.filter(
        expiry_date__isnull=False,
        expiry_date__lt=today,
    ).exclude(asset_status="Not-Available")
    for asset in expired:
        asset.asset_status = "Not-Available"
        asset.save()


def notify_expiring_documents():
    """
    Finds all Expiring Documents and send a notification on the notify_before date.
    """
    from horilla_auth.models import HorillaUser
    from horilla_documents.models import Document

    today = date.today()
    documents = Document.objects.all()
    bot = HorillaUser.objects.filter(username="Horilla Bot").first()
    for document in documents:
        if document.expiry_date:
            expiry_date = document.expiry_date
            notify_date = expiry_date - timedelta(days=document.notify_before)

            if notify_date == today:
                notify.send(
                    bot,
                    recipient=document.employee_id.employee_user_id,
                    verb=gettext_noop(
                        "The document ' %(title)s ' expires in %(notify_before)s days"
                    ),
                    verb_params={
                        "title": str(document.title),
                        "notify_before": str(document.notify_before),
                    },
                    redirect=reverse("asset-category-view"),
                    label="System",
                    icon="information",
                )
            if today >= expiry_date:
                document.is_active = False


def notify_overdue_assignments():
    """
    Notify the borrower and the employee who assigned the asset when it is past
    its due date and not returned. Runs daily, so the reminder repeats until
    the asset is returned.
    """
    from asset.models import AssetAssignment
    from horilla_auth.models import HorillaUser

    today = date.today()
    bot = HorillaUser.objects.filter(username="Horilla Bot").only("id").first()
    if bot is None:
        logger.error(
            "Cannot notify about overdue asset assignments: Horilla Bot is missing."
        )
        return

    overdue = (
        AssetAssignment.objects.filter(
            due_date__isnull=False,
            due_date__lt=today,
            return_date__isnull=True,
        )
        .select_related(
            "asset_id",
            "assigned_to_employee_id__employee_user_id",
            "assigned_by_employee_id__employee_user_id",
        )
    )
    for assignment in overdue:
        recipients = []
        for employee in (
            assignment.assigned_to_employee_id,
            assignment.assigned_by_employee_id,
        ):
            user = getattr(employee, "employee_user_id", None)
            if user is not None and user not in recipients:
                recipients.append(user)

        days_late = (today - assignment.due_date).days
        for recipient in recipients:
            notify.send(
                bot,
                recipient=recipient,
                verb=gettext_noop(
                    "The asset '%(asset_name)s' is %(days)s day(s) overdue for return"
                ),
                verb_params={
                    "asset_name": str(assignment.asset_id.asset_name),
                    "days": str(days_late),
                },
                redirect=reverse("asset-request-allocation-view"),
                label="System",
                icon="information",
            )


PENDING_ACCEPTANCE_DAYS = 3


def notify_pending_acceptances():
    """
    Remind the employee and the assigner when an assigned asset has been
    waiting for acceptance for more than PENDING_ACCEPTANCE_DAYS days. Runs
    daily, so the reminder repeats until the employee responds.
    """
    from asset.models import AssetAssignment
    from horilla_auth.models import HorillaUser

    today = date.today()
    bot = HorillaUser.objects.filter(username="Horilla Bot").only("id").first()
    if bot is None:
        logger.error(
            "Cannot notify about pending asset acceptances: Horilla Bot is missing."
        )
        return

    pending = AssetAssignment.objects.filter(
        acceptance_status="Pending",
        return_date__isnull=True,
        assigned_date__lt=today - timedelta(days=PENDING_ACCEPTANCE_DAYS),
    ).select_related(
        "asset_id",
        "assigned_to_employee_id__employee_user_id",
        "assigned_by_employee_id__employee_user_id",
    )
    for assignment in pending:
        days = (today - assignment.assigned_date).days
        asset_name = str(assignment.asset_id.asset_name)
        employee_user = getattr(
            assignment.assigned_to_employee_id, "employee_user_id", None
        )
        assigner_user = getattr(
            assignment.assigned_by_employee_id, "employee_user_id", None
        )
        if employee_user is not None:
            notify.send(
                bot,
                recipient=employee_user,
                verb=gettext_noop(
                    "Please accept or reject the asset '%(asset_name)s' assigned to you %(days)s day(s) ago"
                ),
                verb_params={"asset_name": asset_name, "days": str(days)},
                redirect=reverse("asset-request-allocation-view"),
                label="System",
                icon="information",
            )
        if assigner_user is not None and assigner_user != employee_user:
            notify.send(
                bot,
                recipient=assigner_user,
                verb=gettext_noop(
                    "%(employee)s has not responded to the asset '%(asset_name)s' for %(days)s day(s)"
                ),
                verb_params={
                    "employee": str(assignment.assigned_to_employee_id),
                    "asset_name": asset_name,
                    "days": str(days),
                },
                redirect=reverse("asset-request-allocation-view"),
                label="System",
                icon="information",
            )


LICENSE_EXPIRY_NOTIFY_DAYS = (60, 30, 7, 0)


def notify_expiring_licenses():
    """
    Notify the renewal_owner 60, 30, and 7 days before a software license
    expires, and on the expiry date itself. Runs daily.
    """
    from asset.models import SoftwareLicense
    from horilla_auth.models import HorillaUser

    today = date.today()
    bot = HorillaUser.objects.filter(username="Horilla Bot").only("id").first()
    if bot is None:
        logger.error(
            "Cannot notify about expiring software licenses: Horilla Bot is missing."
        )
        return

    licenses = SoftwareLicense.objects.filter(
        expiry_date__isnull=False,
        renewal_owner__isnull=False,
    ).select_related("renewal_owner__employee_user_id")

    for license_obj in licenses:
        days_left = (license_obj.expiry_date - today).days
        if days_left not in LICENSE_EXPIRY_NOTIFY_DAYS:
            continue
        owner_user = getattr(license_obj.renewal_owner, "employee_user_id", None)
        if owner_user is None:
            continue
        if days_left == 0:
            verb = gettext_noop(
                "Software license '%(name)s' (%(vendor)s) expires today."
            )
            verb_params = {
                "name": str(license_obj.name),
                "vendor": str(license_obj.vendor),
            }
        else:
            verb = gettext_noop(
                "Software license '%(name)s' (%(vendor)s) expires in %(days)s day(s)."
            )
            verb_params = {
                "name": str(license_obj.name),
                "vendor": str(license_obj.vendor),
                "days": str(days_left),
            }
        notify.send(
            bot,
            recipient=owner_user,
            verb=verb,
            verb_params=verb_params,
            redirect=reverse("software-license-view"),
            label="System",
            icon="information",
        )


register_job(notify_expiring_assets, "interval", days=1)
register_job(notify_expiring_documents, "interval", hours=4)
register_job(mark_expired_assets, "interval", days=1)
register_job(notify_overdue_assignments, "interval", days=1)
register_job(notify_pending_acceptances, "interval", days=1)
register_job(notify_expiring_licenses, "interval", days=1)
