from django.apps import AppConfig


class FrontendConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'frontend'

    def ready(self):
        from . import checks  # noqa: F401
        from . import lobby_events  # noqa: F401
