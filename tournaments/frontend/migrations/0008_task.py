import uuid

from django.db import migrations, models
import django.utils.timezone


def seed_tasks(apps, schema_editor):
    Task = apps.get_model('frontend', 'Task')
    AdminGameCommand = apps.get_model('gamelink', 'AdminGameCommand')
    database = schema_editor.connection.alias
    Task.objects.using(database).get_or_create(
        key='expire-unstarted-games',
        defaults={'name': 'expire_unstarted_games'},
    )
    command_ids = AdminGameCommand.objects.using(database).filter(status='pending').values_list('pk', flat=True)
    for command_id in command_ids.iterator():
        Task.objects.using(database).get_or_create(
            key=f'admin-command:{command_id}',
            defaults={
                'name': 'deliver_admin_command',
                'kwargs': {'command_id': str(command_id)},
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('frontend', '0007_delivery_failure_timestamps'),
        ('gamelink', '0004_admingamecommand'),
    ]

    operations = [
        migrations.CreateModel(
            name='Task',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('key', models.CharField(max_length=255, unique=True)),
                ('name', models.CharField(choices=[('deliver_admin_command', 'Deliver admin command'), ('expire_unstarted_games', 'Expire unstarted games')], max_length=40)),
                ('kwargs', models.JSONField(default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('done', 'Done')], default='pending', max_length=8)),
                ('run_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('lease_token', models.UUIDField(blank=True, null=True)),
                ('locked_until', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True)),
                ('last_finished_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ('run_at', 'created_at', 'id'),
                'indexes': [
                    models.Index(fields=['status', 'run_at'], name='task_status_run_at_idx'),
                    models.Index(fields=['status', 'locked_until'], name='task_status_lease_idx'),
                ],
            },
        ),
        migrations.RunPython(seed_tasks, migrations.RunPython.noop),
    ]
