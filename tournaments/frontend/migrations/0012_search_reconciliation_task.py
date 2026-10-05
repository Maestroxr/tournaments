from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('frontend', '0011_fixture_push_delivery')]
    operations = [migrations.AlterField(
        model_name='task', name='name', field=models.CharField(max_length=40, choices=[
            ('reconcile_searches', 'Reconcile unmatched searches'),
            ('deliver_admin_command', 'Deliver admin command'),
            ('expire_unstarted_games', 'Expire unstarted games'),
            ('start_scheduled_tournaments', 'Start scheduled tournaments'),
            ('expire_tournament_entry_deadlines', 'Expire tournament entry deadlines'),
        ]),
    )]
