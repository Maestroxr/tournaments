from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('frontend', '0006_alter_tablepushdelivery_kind')]

    operations = [
        migrations.AddField(
            model_name='pushdelivery',
            name='last_failure_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tablepushdelivery',
            name='last_failure_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
