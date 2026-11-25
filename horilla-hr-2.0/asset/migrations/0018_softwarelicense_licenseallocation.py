import datetime
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("asset", "0017_assetrequest_intake_details"),
        ("employee", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SoftwareLicense",
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
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name="Created At"
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Active"),
                ),
                ("name", models.CharField(max_length=255, verbose_name="License Name")),
                ("vendor", models.CharField(max_length=255, verbose_name="Vendor")),
                (
                    "license_key",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=255,
                        verbose_name="License Key",
                    ),
                ),
                (
                    "total_seats",
                    models.PositiveIntegerField(default=1, verbose_name="Total Seats"),
                ),
                ("purchase_date", models.DateField(verbose_name="Purchase Date")),
                (
                    "expiry_date",
                    models.DateField(blank=True, null=True, verbose_name="Expiry Date"),
                ),
                (
                    "cost",
                    models.DecimalField(
                        decimal_places=2, default=0, max_digits=10, verbose_name="Cost"
                    ),
                ),
                ("notes", models.TextField(blank=True, null=True, verbose_name="Notes")),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created By",
                    ),
                ),
                (
                    "modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Modified By",
                    ),
                ),
                (
                    "renewal_owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="owned_software_licenses",
                        to="employee.employee",
                        verbose_name="Renewal Owner",
                    ),
                ),
            ],
            options={
                "verbose_name": "Software License",
                "verbose_name_plural": "Software Licenses",
                "ordering": ["expiry_date", "name"],
            },
        ),
        migrations.CreateModel(
            name="LicenseAllocation",
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
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, null=True, verbose_name="Created At"
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Active"),
                ),
                (
                    "allocated_date",
                    models.DateField(
                        default=datetime.date.today, verbose_name="Allocated Date"
                    ),
                ),
                (
                    "asset",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="software_license_allocations",
                        to="asset.asset",
                        verbose_name="Asset / Device",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Created By",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="software_license_allocations",
                        to="employee.employee",
                        verbose_name="Employee",
                    ),
                ),
                (
                    "license",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allocations",
                        to="asset.softwarelicense",
                        verbose_name="Software License",
                    ),
                ),
                (
                    "modified_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_modified_by",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Modified By",
                    ),
                ),
            ],
            options={
                "verbose_name": "License Allocation",
                "verbose_name_plural": "License Allocations",
                "ordering": ["-allocated_date", "-id"],
            },
        ),
    ]
