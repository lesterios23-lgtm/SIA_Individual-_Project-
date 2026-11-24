from django.db import migrations, models


def accept_existing_assignments(apps, schema_editor):
    """
    Allocations that exist before this feature were already handed over, so
    they count as accepted instead of flooding everyone with Pending items.
    """
    AssetAssignment = apps.get_model("asset", "AssetAssignment")
    AssetAssignment._default_manager.update(acceptance_status="Accepted")


class Migration(migrations.Migration):

    dependencies = [
        ("asset", "0015_assetservicerequest_fault_category_date_of_issue"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetassignment",
            name="acceptance_status",
            field=models.CharField(
                choices=[
                    ("Pending", "Pending"),
                    ("Accepted", "Accepted"),
                    ("Rejected", "Rejected"),
                ],
                default="Pending",
                max_length=20,
                verbose_name="Acceptance",
            ),
        ),
        migrations.AddField(
            model_name="assetassignment",
            name="responded_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Responded On"
            ),
        ),
        migrations.AddField(
            model_name="assetassignment",
            name="acceptance_note",
            field=models.TextField(
                blank=True, null=True, verbose_name="Response Note"
            ),
        ),
        migrations.RunPython(accept_existing_assignments, migrations.RunPython.noop),
    ]
