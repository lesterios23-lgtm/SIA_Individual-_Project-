import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("employee", "0009_alter_actiontype_is_active_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="OutboundEvent",
            fields=[
                (
                    "event_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "source_system",
                    models.CharField(default="hr", max_length=32),
                ),
                ("event_type", models.CharField(max_length=64)),
                ("correlation_id", models.CharField(max_length=128)),
                ("external_id", models.CharField(blank=True, max_length=128)),
                ("payload", models.JSONField()),
                ("payload_hash", models.CharField(db_index=True, max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sending", "Sending"),
                            ("delivered", "Delivered to gateway"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                            ("blocked", "Blocked by missing HR data"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveSmallIntegerField(default=5)),
                (
                    "next_attempt_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_http_status",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "gateway_status",
                    models.CharField(blank=True, max_length=32, null=True),
                ),
                ("last_error", models.TextField(blank=True, null=True)),
                (
                    "last_error_code",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                ("last_error_fields", models.JSONField(blank=True, null=True)),
                ("response_body", models.TextField(blank=True, null=True)),
                ("occurred_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["status", "next_attempt_at"],
                        name="limbus_out_status_next_idx",
                    ),
                    models.Index(
                        fields=["event_type", "external_id", "payload_hash"],
                        name="limbus_out_dedupe_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="InboundEvent",
            fields=[
                (
                    "event_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("source_system", models.CharField(max_length=32)),
                ("event_type", models.CharField(max_length=64)),
                ("correlation_id", models.CharField(max_length=128)),
                ("external_id", models.CharField(max_length=128)),
                ("payload", models.JSONField()),
                ("occurred_at", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("received", "Received"),
                            ("processed", "Processed"),
                            ("exception", "Needs HR follow-up"),
                            ("ignored", "Ignored"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="received",
                        max_length=16,
                    ),
                ),
                (
                    "resolution",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "operator_external_id",
                    models.CharField(blank=True, max_length=128, null=True),
                ),
                ("error", models.TextField(blank=True, null=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "resolved_employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="employee.employee",
                    ),
                ),
            ],
            options={
                "ordering": ("-received_at",),
            },
        ),
        migrations.CreateModel(
            name="OutboundEventAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("attempt_no", models.PositiveIntegerField()),
                ("started_at", models.DateTimeField()),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "http_status",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("sent", "Sent"),
                            ("retry", "Scheduled for retry"),
                            ("failed", "Failed permanently"),
                        ],
                        max_length=16,
                    ),
                ),
                ("error", models.TextField(blank=True, null=True)),
                ("response_body", models.TextField(blank=True, null=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attempts",
                        to="limbus_integration.outboundevent",
                    ),
                ),
            ],
            options={
                "ordering": ("attempt_no",),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event", "attempt_no"),
                        name="limbus_attempt_unique",
                    )
                ],
            },
        ),
    ]
