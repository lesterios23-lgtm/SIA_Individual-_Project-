from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("asset", "0018_softwarelicense_licenseallocation"),
    ]

    operations = [
        migrations.AddField(
            model_name="asset",
            name="approval_reference",
            field=models.CharField(
                blank=True,
                default="",
                max_length=100,
                verbose_name="Approval Reference",
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="invoice_number",
            field=models.CharField(
                blank=True, default="", max_length=100, verbose_name="Invoice Number"
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="purchase_reference",
            field=models.CharField(
                blank=True,
                default="",
                max_length=100,
                verbose_name="Purchase Reference",
            ),
        ),
        migrations.AddField(
            model_name="asset",
            name="received_date",
            field=models.DateField(blank=True, null=True, verbose_name="Received Date"),
        ),
        migrations.AddField(
            model_name="asset",
            name="supplier_name",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Supplier Name"
            ),
        ),
    ]
