from django.db import migrations, models
from django.db.models import Count


def require_unique_prizes(apps, schema_editor):
    ledger = apps.get_model('tournaments', 'WalletTransaction').objects.using(schema_editor.connection.alias)
    for kind, field in (
        ('tournament_prize', 'tournament_id'),
        ('head_to_head_prize', 'head_to_head_table_id'),
    ):
        duplicates = list(ledger.filter(kind=kind, **{f'{field}__isnull': False})
                          .values(field).annotate(count=Count('pk')).filter(count__gt=1)[:20])
        if duplicates:
            # Financial history must be audited, never silently deleted or
            # merged to make a migration succeed. The migration is atomic.
            raise RuntimeError(f'Duplicate {kind} entries require review before migration: {duplicates}')


class Migration(migrations.Migration):
    dependencies = [('tournaments', '0033_tournament_entry_deadline_paused')]
    operations = [
        migrations.RunPython(require_unique_prizes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.UniqueConstraint(
                fields=('tournament',), condition=models.Q(kind='tournament_prize'),
                name='wallet_one_tournament_prize',
            ),
        ),
        migrations.AddConstraint(
            model_name='wallettransaction',
            constraint=models.UniqueConstraint(
                fields=('head_to_head_table',), condition=models.Q(kind='head_to_head_prize'),
                name='wallet_one_table_prize',
            ),
        ),
    ]
