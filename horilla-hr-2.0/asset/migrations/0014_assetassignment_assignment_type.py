from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("asset", "0013_assetassignment_due_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetassignment",
            name="assignment_type",
            field=models.CharField(
                choices=[
                    ("Permanent", "Permanent"),
                    ("Temporary Loan", "Temporary Loan"),
                ],
                default="Permanent",
                max_length=20,
                verbose_name="Assignment Type",
            ),
        ),
    ]
