import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('frontend', '0009_alter_task_name'),
        ('tournaments', '0032_headtoheadtable_guest_ready_at_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TournamentReminderDelivery',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scheduled_start', models.DateTimeField()),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('next_attempt_at', models.DateTimeField()),
                ('last_failure_at', models.DateTimeField(blank=True, null=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('discarded_at', models.DateTimeField(blank=True, null=True)),
                ('subscription', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='frontend.pushsubscription')),
                ('tournament', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tournaments.tournament')),
            ],
            options={
                'constraints': [models.UniqueConstraint(
                    fields=('subscription', 'tournament', 'scheduled_start'),
                    name='unique_tournament_reminder',
                )],
            },
        ),
    ]
