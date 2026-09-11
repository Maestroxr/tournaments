from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('frontend', '0002_push_notifications'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name='GoogleIdentity',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('subject', models.CharField(max_length=255, unique=True)),
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='google_identity', to=settings.AUTH_USER_MODEL)),
        ],
    )]
