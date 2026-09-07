from django.db import migrations, models
import django.db.models.deletion


def create_existing_registrations(apps, schema_editor):
    Participation = apps.get_model('tournaments', 'Participation')
    TournamentRegistration = apps.get_model('tournaments', 'TournamentRegistration')
    registrations = []
    for participation in Participation.objects.all().iterator():
        registrations.append(TournamentRegistration(
            tournament_id=participation.tournament_id,
            participant_id=participation.participant_id,
            status='disqualified' if participation.disqualified_at else 'registered',
            payment_status='paid',
        ))
    TournamentRegistration.objects.bulk_create(registrations, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0012_tournament_lifecycle'),
    ]

    operations = [
        migrations.AddField(
            model_name='tournament',
            name='registration_closed_reason',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
        migrations.CreateModel(
            name='TournamentRegistration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('registered', 'Registered'), ('waitlisted', 'Waitlisted'), ('withdrawn', 'Withdrawn'), ('disqualified', 'Disqualified')], default='registered', max_length=20)),
                ('payment_status', models.CharField(choices=[('paid', 'Paid'), ('unpaid', 'Unpaid'), ('waived', 'Waived'), ('refunded', 'Refunded')], default='paid', max_length=20)),
                ('checked_in_at', models.DateTimeField(blank=True, null=True)),
                ('withdrawn_at', models.DateTimeField(blank=True, null=True)),
                ('internal_note', models.TextField(blank=True)),
                ('registered_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('participant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tournament_registrations', to='tournaments.participant')),
                ('tournament', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='registrations', to='tournaments.tournament')),
            ],
            options={
                'ordering': ('tournament', 'registered_at', 'id'),
            },
        ),
        migrations.AddConstraint(
            model_name='tournamentregistration',
            constraint=models.UniqueConstraint(fields=('tournament', 'participant'), name='unique_tournament_registration'),
        ),
        migrations.RunPython(create_existing_registrations, migrations.RunPython.noop),
    ]
