import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('frontend', '0012_search_reconciliation_task')]

    operations = [
        migrations.CreateModel(
            name='LobbyRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('resource', models.CharField(max_length=16)),
                ('scope', models.CharField(max_length=160)),
                ('generation', models.UUIDField(default=uuid.uuid4, editable=False)),
                ('sequence', models.PositiveBigIntegerField(default=0)),
            ],
            options={'constraints': [models.UniqueConstraint(
                fields=('resource', 'scope'), name='unique_lobby_revision_scope')]},
        ),
    ]
