from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('tournaments', '0021_directplaysettings_game_rules')]
    operations = [migrations.AddField(model_name='headtoheadtable', name='quick_stakes', field=models.JSONField(default=list, blank=True))]
