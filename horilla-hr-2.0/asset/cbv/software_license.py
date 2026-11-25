"""
CBV views for Software License Register & Seat Allocation (Mod 6 - P9, P10).
"""

from typing import Any

from django.contrib import messages
from django.http import HttpResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from django.views.generic.edit import DeleteView

from asset.filters import SoftwareLicenseFilter
from asset.forms import LicenseAllocationForm, SoftwareLicenseForm
from asset.models import LicenseAllocation, SoftwareLicense
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
class SoftwareLicenseView(TemplateView):
    """
    Main page wrapper for the Software Licenses register.
    """

    template_name = "cbv/software_license/software_license.html"


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class SoftwareLicenseNav(HorillaNavView):
    """
    Nav bar with search, Expiring Soon / Expired filter, and Create button.
    """

    nav_title = _("Software Licenses")
    filter_instance = SoftwareLicenseFilter()
    filter_form_context_name = "form"
    filter_body_template = "cbv/software_license/software_license_filter.html"
    search_swap_target = "#listContainer"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("software-license-list")
        if self.request.user.has_perm("asset.add_asset"):
            self.create_attrs = f"""
                data-toggle="oh-modal-toggle"
                data-target="#genericModal"
                hx-target="#genericModalBody"
                hx-get="{reverse('software-license-create')}"
            """


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class SoftwareLicenseListView(HorillaListView):
    """
    List view of software licenses with seat usage and renewal status.
    """

    model = SoftwareLicense
    filter_class = SoftwareLicenseFilter

    columns = [
        (_("License Name"), "name"),
        (_("Vendor"), "vendor"),
        (_("Seats Used / Total"), "seats_col"),
        (_("Expiry Date"), "expiry_date"),
        (_("Renewal Owner"), "renewal_owner"),
        (_("Status"), "status_col"),
    ]

    sortby_mapping = [
        (_("License Name"), "name"),
        (_("Vendor"), "vendor"),
        (_("Expiry Date"), "expiry_date"),
        (_("Renewal Owner"), "renewal_owner__employee_first_name"),
    ]

    row_status_indications = [
        (
            "green--dot",
            _("Active"),
            """
            onclick="
                $('#applyFilter').closest('form').find('[name=status]').val('Active');
                $('#applyFilter').click();
            "
            """,
        ),
        (
            "yellow--dot",
            _("Expiring Soon"),
            """
            onclick="
                $('#applyFilter').closest('form').find('[name=status]').val('Expiring Soon');
                $('#applyFilter').click();
            "
            """,
        ),
        (
            "red--dot",
            _("Expired"),
            """
            onclick="
                $('#applyFilter').closest('form').find('[name=status]').val('Expired');
                $('#applyFilter').click();
            "
            """,
        ),
    ]
    row_status_class = "{row_status_class}"

    header_attrs = {"action": """ style = "width:150px !important" """}
    action_method = "actions"

    row_attrs = """
        hx-get='{get_detail_url}?instance_ids={ordered_ids}'
        hx-target="#genericModalBody"
        data-target="#genericModal"
        data-toggle="oh-modal-toggle"
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.search_url = reverse("software-license-list")
        self.view_id = "SoftwareLicenseList"


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.add_asset"), name="dispatch")
class SoftwareLicenseFormView(HorillaFormView):
    """
    Create or edit a SoftwareLicense.
    """

    model = SoftwareLicense
    form_class = SoftwareLicenseForm
    new_display_title = _("Create Software License")

    def dispatch(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if pk and not SoftwareLicense.objects.filter(pk=pk).exists():
            messages.error(request, _("Software license not found."))
            return HorillaRedirect(request)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.form.instance.pk:
            self.form_class.verbose_name = _("Update Software License")
        return context

    def form_valid(self, form: SoftwareLicenseForm) -> HttpResponse:
        if form.is_valid():
            message = (
                _("Software license updated successfully.")
                if form.instance.pk
                else _("Software license created successfully.")
            )
            form.save()
            messages.success(self.request, message)
            return self.HttpResponse()
        return super().form_valid(form)


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.view_asset"), name="dispatch")
class SoftwareLicenseDetailView(HorillaDetailedView):
    """
    Detail modal for a SoftwareLicense, including its seat allocations.
    """

    model = SoftwareLicense
    title = _("Software License Details")
    header = {
        "title": "name",
        "subtitle": "vendor",
    }
    body = [
        (_("Vendor"), "vendor"),
        (_("License Key"), "license_key"),
        (_("Seats Used / Total"), "seats_col"),
        (_("Status"), "status_col"),
        (_("Purchase Date"), "purchase_date"),
        (_("Expiry Date"), "expiry_date"),
        (_("Cost"), "cost"),
        (_("Renewal Owner"), "renewal_owner"),
        (_("Notes"), "notes"),
        (_("Allocated Seats"), "allocations_display", True),
    ]
    cols = {
        "notes": 12,
        "allocations_display": 12,
    }
    action_method = "detail_actions"


@method_decorator(login_required, name="dispatch")
@method_decorator(require_http_methods(["POST"]), name="dispatch")
@method_decorator(permission_required("asset.delete_asset"), name="dispatch")
class SoftwareLicenseDeleteView(DeleteView):
    """
    Delete a SoftwareLicense record.
    """

    model = SoftwareLicense

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        messages.success(request, _("Software license deleted successfully."))
        return HorillaFormView.HttpResponse()


@method_decorator(login_required, name="dispatch")
@method_decorator(permission_required("asset.change_asset"), name="dispatch")
class LicenseAllocationFormView(HorillaFormView):
    """
    Allocate a license seat to an employee and/or asset.
    """

    model = LicenseAllocation
    form_class = LicenseAllocationForm
    new_display_title = _("Allocate Software License Seat")

    def get_initial(self):
        initial = super().get_initial()
        license_id = self.kwargs.get("license_id") or self.request.GET.get("license")
        if license_id:
            initial["license"] = license_id
        return initial

    def form_valid(self, form: LicenseAllocationForm) -> HttpResponse:
        if form.is_valid():
            form.save()
            messages.success(self.request, _("License seat allocated successfully."))
            return self.HttpResponse()
        return super().form_valid(form)


@method_decorator(login_required, name="dispatch")
@method_decorator(require_http_methods(["POST"]), name="dispatch")
@method_decorator(permission_required("asset.change_asset"), name="dispatch")
class LicenseAllocationDeleteView(DeleteView):
    """
    Remove a seat allocation from a SoftwareLicense.
    """

    model = LicenseAllocation

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        messages.success(request, _("License seat allocation removed."))
        return HorillaFormView.HttpResponse()
