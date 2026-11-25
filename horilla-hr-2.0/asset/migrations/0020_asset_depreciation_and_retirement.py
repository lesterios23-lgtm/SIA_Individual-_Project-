from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import horilla.models


class Migration(migrations.Migration):

    dependencies = [
        ("asset", "0019_asset_procurement_intake"),
        ("employee", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="salvage_value",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10,
                verbose_name="Salvage Value",
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="useful_life_years",
            field=models.PositiveIntegerField(
                default=3, verbose_name="Useful Life (Years)"
            ),
        ),
        migrations.CreateModel(
            name="AssetRetirement",
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
                    "proposed_action",
                    models.CharField(
                        choices=[
                            ("Repair", "Repair"),
                            ("Reuse", "Reuse"),
                            ("Store", "Store"),
                            ("Donate", "Donate"),
                            ("Dispose", "Dispose"),
                        ],
                        default="Dispose",
                        max_length=20,
                        verbose_name="Proposed Action",
                    ),
                ),
                (
                    "sanitization_method",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=255,
                        verbose_name="Sanitization Method",
                    ),
                ),
                (
                    "sanitization_date",
                    models.DateField(
                        blank=True, null=True, verbose_name="Sanitization Date"
                    ),
                ),
                (
                    "sanitization_verified",
                    models.BooleanField(
                        default=False, verbose_name="Sanitization Verified"
                    ),
                ),
                (
                    "evidence_file",
                    models.FileField(
                        blank=True,
                        null=True,
                        upload_to=horilla.models.upload_path,
                        verbose_name="Sanitization Evidence",
                    ),
                ),
                (
                    "approval_date",
                    models.DateField(
                        blank=True, null=True, verbose_name="Approval Date"
                    ),
                ),
                (
                    "final_disposition",
                    models.TextField(
                        blank=True, null=True, verbose_name="Final Disposition"
                    ),
                ),
                ("closed", models.BooleanField(default=False, verbose_name="Closed")),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_asset_retirements",
                        to="employee.employee",
                        verbose_name="Approved By",
                    ),
                ),
                (
                    "asset",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="retirement",
                        to="asset.asset",
                        verbose_name="Asset",
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
                    "sanitization_technician",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sanitized_assets",
                        to="employee.employee",
                        verbose_name="Sanitization Technician",
                    ),
                ),
            ],
            options={
                "verbose_name": "Asset Retirement",
                "verbose_name_plural": "Asset Retirements",
                "ordering": ["-id"],
            },
        ),
    ]
