from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='AccountEmail', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('email', models.EmailField(max_length=254, unique=True)),
        ('verified_at', models.DateTimeField(blank=True, null=True)),
        ('last_sent_at', models.DateTimeField(blank=True, null=True)),
        ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='account_email', to=settings.AUTH_USER_MODEL)),
    ])]
