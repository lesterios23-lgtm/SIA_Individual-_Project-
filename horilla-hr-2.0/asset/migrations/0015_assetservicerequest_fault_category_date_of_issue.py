import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("asset", "0014_assetassignment_assignment_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetservicerequest",
            name="fault_category",
            field=models.CharField(
                choices=[
                    ("Hardware", "Hardware"),
                    ("Software", "Software"),
                    ("Network", "Network"),
                    ("Battery/Power", "Battery/Power"),
                    ("Other", "Other"),
                ],
                default="Other",
                max_length=20,
                verbose_name="Fault Category",
            ),
        ),
        migrations.AddField(
            model_name="assetservicerequest",
            name="date_of_issue",
            field=models.DateField(
                default=datetime.date.today, verbose_name="Date of Issue"
            ),
        ),
    ]
