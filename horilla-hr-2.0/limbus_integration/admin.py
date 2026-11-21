"""Read-only admin views for the HR integration audit trail."""

from django.contrib import admin

from .models import InboundEvent, OutboundEvent, OutboundEventAttempt


class ReadOnlyAdmin(admin.ModelAdmin):
    """Audit rows are immutable in the admin; operators use the commands."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OutboundEventAttemptInline(admin.TabularInline):
    model = OutboundEventAttempt
    extra = 0
    can_delete = False
    readonly_fields = (
        "attempt_no",
        "started_at",
        "finished_at",
        "http_status",
        "outcome",
        "error",
        "response_body",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(OutboundEvent)
class OutboundEventAdmin(ReadOnlyAdmin):
    list_display = (
        "event_id",
        "event_type",
        "external_id",
        "status",
        "attempt_count",
        "last_http_status",
        "gateway_status",
        "created_at",
    )
    list_filter = ("status", "event_type", "source_system")
    search_fields = ("event_id", "external_id", "correlation_id")
    readonly_fields = (
        "event_id",
        "source_system",
        "event_type",
        "correlation_id",
        "external_id",
        "payload",
        "payload_hash",
        "status",
        "attempt_count",
        "max_attempts",
        "next_attempt_at",
        "last_attempt_at",
        "last_http_status",
        "gateway_status",
        "last_error",
        "last_error_code",
        "last_error_fields",
        "response_body",
        "occurred_at",
        "created_at",
        "updated_at",
        "delivered_at",
        "processed_at",
    )
    inlines = (OutboundEventAttemptInline,)


@admin.register(OutboundEventAttempt)
class OutboundEventAttemptAdmin(ReadOnlyAdmin):
    list_display = (
        "event",
        "attempt_no",
        "outcome",
        "http_status",
        "started_at",
        "finished_at",
    )
    list_filter = ("outcome", "http_status")
    search_fields = ("event__event_id", "event__external_id")


@admin.register(InboundEvent)
class InboundEventAdmin(ReadOnlyAdmin):
    list_display = (
        "event_id",
        "event_type",
        "external_id",
        "status",
        "resolution",
        "operator_external_id",
        "resolved_employee",
        "received_at",
    )
    list_filter = ("status", "resolution", "event_type", "source_system")
    search_fields = ("event_id", "external_id", "correlation_id", "operator_external_id")
    readonly_fields = (
        "event_id",
        "source_system",
        "event_type",
        "correlation_id",
        "external_id",
        "payload",
        "occurred_at",
        "status",
        "resolution",
        "operator_external_id",
        "resolved_employee",
        "error",
        "received_at",
        "processed_at",
    )
