"""
CBV views for Asset Retirement Checklist & Depreciation Report (Mod 7 - P11, P12).
"""

import csv
from decimal import Decimal
from typing import Any

from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.decorators.http import require_http_methods
from django.views.generic.edit import DeleteView

from asset.filters import AssetRetirementFilter
from asset.forms import AssetRetirementForm
from asset.models import Asset, AssetRetirement
from horilla.http.response import HorillaRedirect
from horilla_views.cbv_methods import login_required, permission_required
from horilla_views.generic.cbv.views import (
    HorillaDetailedView,
    HorillaFormView,
    HorillaListView,
    HorillaNavView,
    TemplateView,
)


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class AssetRetirementView(TemplateView):
    """
    Main page wrapper for Asset Retirement & Disposal Checklist.
    """

    template_name = "cbv/asset_retirement/asset_retirement.html"


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class AssetRetirementNav(HorillaNavView):
    """
    Nav bar for Asset Retirement page.
    """

    nav_title = _("Asset Retirement")
    filter_instance = AssetRetirementFilter()
    filter_form_context_name = "form"
    filter_body_template = "cbv/asset_retirement/asset_retirement_filter.html"
    search_swap_target = "#listContainer"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("asset-retirement-list")
        if self.request.user.has_perm("asset.change_asset"):
            self.create_attrs = f"""
                data-toggle="oh-modal-toggle"
                data-target="#genericModal"
                hx-target="#genericModalBody"
                hx-get="{reverse('asset-retirement-create')}"
            """


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class AssetRetirementListView(HorillaListView):
    """
    List view of AssetRetirement records.
    """

    model = AssetRetirement
    filter_class = AssetRetirementFilter

    columns = [
        (_("Asset"), "asset"),
        (_("Proposed Action"), "proposed_action"),
        (_("Sanitization"), "sanitization_col"),
        (_("Approved By"), "approved_by"),
        (_("Status"), "status_col"),
    ]

    sortby_mapping = [
        (_("Asset"), "asset__asset_name"),
        (_("Proposed Action"), "proposed_action"),
        (_("Status"), "closed"),
    ]

    header_attrs = {"action": """ style = "width:120px !important" """}
    action_method = "actions"

    row_attrs = """
        hx-get='{get_detail_url}?instance_ids={ordered_ids}'
        hx-target="#genericModalBody"
        data-target="#genericModal"
        data-toggle="oh-modal-toggle"
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("asset-retirement-list")
        self.view_id = "AssetRetirementList"


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.change_asset"), name="dispatch")
class AssetRetirementFormView(HorillaFormView):
    """
    Create or update an AssetRetirement checklist record.
    """

    model = AssetRetirement
    form_class = AssetRetirementForm
    new_display_title = _("Create Asset Retirement")

    def dispatch(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if pk and not AssetRetirement.objects.filter(pk=pk).exists():
            messages.error(request, _("Asset retirement record not found."))
            return HorillaRedirect(request)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.form.instance.pk:
            self.form_class.verbose_name = _("Update Asset Retirement")
        return context

    def form_valid(self, form: AssetRetirementForm) -> HttpResponse:
        if form.is_valid():
            is_update = bool(form.instance.pk)
            instance = form.save()
            if instance.closed and instance.proposed_action in ("Donate", "Dispose"):
                Asset.objects.entire().filter(pk=instance.asset_id).update(
                    asset_status="Not-Available"
                )
            message = (
                _("Asset retirement updated successfully.")
                if is_update
                else _("Asset retirement created successfully.")
            )
            messages.success(self.request, message)
            return self.HttpResponse()
        return super().form_valid(form)


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class AssetRetirementDetailView(HorillaDetailedView):
    """
    Detail modal for an AssetRetirement record.
    """

    model = AssetRetirement
    title = _("Asset Retirement Details")
    header = {
        "title": "asset",
        "subtitle": "proposed_action",
    }
    body = [
        (_("Proposed Action"), "proposed_action"),
        (_("Status"), "status_col"),
        (_("Sanitization Method"), "sanitization_method"),
        (_("Sanitization Date"), "sanitization_date"),
        (_("Sanitization Technician"), "sanitization_technician"),
        (_("Sanitization Status"), "sanitization_col"),
        (_("Approved By"), "approved_by"),
        (_("Approval Date"), "approval_date"),
        (_("Final Disposition"), "final_disposition"),
    ]
    cols = {
        "final_disposition": 12,
    }
    action_method = "detail_actions"


@method_decorator(login_required, name="dispatch")
@method_decorator(require_http_methods(["POST"]), name="dispatch")
@method_decorator(permission_required("asset.delete_asset"), name="dispatch")
class AssetRetirementDeleteView(DeleteView):
    """
    Delete an AssetRetirement record.
    """

    model = AssetRetirement

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        messages.success(request, _("Asset retirement deleted successfully."))
        return HorillaFormView.HttpResponse()


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class DepreciationReportView(TemplateView):
    """
    Straight-line depreciation report across all assets with CSV export (Mod 7 - P12).
    """

    template_name = "cbv/asset_retirement/depreciation_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        assets = Asset.objects.select_related("asset_category_id").order_by(
            "asset_purchase_date", "asset_name"
        )
        rows = []
        total_cost = Decimal("0.00")
        total_accumulated = Decimal("0.00")
        total_book_value = Decimal("0.00")

        for asset in assets:
            cost = Decimal(asset.asset_purchase_cost or 0)
            yearly = asset.annual_depreciation
            accum = asset.accumulated_depreciation
            book = asset.current_book_value
            total_cost += cost
            total_accumulated += accum
            total_book_value += book
            rows.append(
                {
                    "asset": asset,
                    "yearly_depreciation": yearly,
                    "accumulated_depreciation": accum,
                    "book_value": book,
                }
            )

        context.update(
            {
                "rows": rows,
                "total_assets": len(rows),
                "total_cost": total_cost,
                "total_accumulated": total_accumulated,
                "total_book_value": total_book_value,
            }
        )
        return context


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class DepreciationReportExportCSVView(View):
    """
    Export the Asset Depreciation Report as a UTF-8 CSV file for Finance / Akaunting reconciliation.
    """

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            'attachment; filename="asset_depreciation_report.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "Asset",
                "Serial No.",
                "Category",
                "Purchase Date",
                "Purchase Cost",
                "Useful Life (Years)",
                "Salvage Value",
                "Yearly Depreciation",
                "Accumulated Depreciation",
                "Book Value",
            ]
        )
        assets = Asset.objects.select_related("asset_category_id").order_by(
            "asset_purchase_date", "asset_name"
        )
        for asset in assets:
            writer.writerow(
                [
                    asset.asset_name,
                    asset.asset_tracking_id,
                    str(asset.asset_category_id),
                    asset.asset_purchase_date.isoformat()
                    if asset.asset_purchase_date
                    else "",
                    f"{Decimal(asset.asset_purchase_cost or 0):.2f}",
                    asset.useful_life_years,
                    f"{Decimal(asset.salvage_value or 0):.2f}",
                    f"{asset.annual_depreciation:.2f}",
                    f"{asset.accumulated_depreciation:.2f}",
                    f"{asset.current_book_value:.2f}",
                ]
            )
        return response
