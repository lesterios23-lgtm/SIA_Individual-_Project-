from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("asset", "0016_assetassignment_acceptance"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetrequest",
            name="needed_date",
            field=models.DateField(blank=True, null=True, verbose_name="Needed Date"),
        ),
        migrations.AddField(
            model_name="assetrequest",
            name="priority",
            field=models.CharField(
                choices=[("Low", "Low"), ("Medium", "Medium"), ("High", "High")],
                default="Medium",
                max_length=20,
                verbose_name="Priority",
            ),
        ),
        migrations.AddField(
            model_name="assetrequest",
            name="purpose",
            field=models.TextField(blank=True, null=True, verbose_name="Purpose"),
        ),
        migrations.AddField(
            model_name="assetrequest",
            name="work_location",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Oriental Mindoro HQ", "Oriental Mindoro HQ"),
                    ("Metro Manila Office", "Metro Manila Office"),
                    ("Visayas/Mindanao Hub", "Visayas/Mindanao Hub"),
                    ("Remote", "Remote"),
                ],
                max_length=50,
                null=True,
                verbose_name="Work Location",
            ),
        ),
    ]
