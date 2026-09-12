from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('frontend', '0004_table_push_delivery')]

    operations = [migrations.CreateModel(
        name='PushWorkerStatus',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('last_seen_at', models.DateTimeField()),
            ('expected_by', models.DateTimeField()),
        ],
    )]
