from django.apps import AppConfig


class GamelinkConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'gamelink'

    def ready(self):
        from . import checks  # noqa: F401  (registers the boot-time system checks)
