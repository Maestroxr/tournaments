from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0011_match_administration'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='registration_closed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tournament',
            name='draw_order',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='tournament',
            name='draw_generated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tournament',
            name='draw_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tournament',
            name='results_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
