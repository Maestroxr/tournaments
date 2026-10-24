"""Explicit PostgreSQL and shared Redis for container APIs and workers."""

from django.core.exceptions import ImproperlyConfigured

from tournaments.settings.common import *

SECRET_KEY = os.environ['SECRET_KEY']
DEBUG = os.environ.get('DEBUG', '0') == '1'
ALLOWED_HOSTS = env_list('ALLOWED_HOSTS')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')
DATABASES = {'default': postgresql_database(os.environ, required=True, require_host=True)}
if CHANNEL_LAYER_BACKEND != 'redis':
    raise ImproperlyConfigured('Docker requires the shared Redis channel layer.')
STATIC_ROOT = '/data/static'
MEDIA_ROOT = '/data/media'
MEDIA_URL = '/media/'
if not DEBUG:
    STATIC_URL = '/tournaments-static/'
    MEDIA_URL = '/tournaments-media/'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_CONTENT_TYPE_NOSNIFF = True

# Keep incident loggers; also expose request failures and worker logs in Docker.
LOGGING['handlers']['incident_console']['level'] = os.environ.get('APP_LOG_LEVEL', 'INFO')
LOGGING['loggers']['django'] = {
    'handlers': ['incident_console'], 'level': 'INFO', 'propagate': False,
}
LOGGING['root'] = {
    'handlers': ['incident_console'],
    'level': os.environ.get('APP_LOG_LEVEL', 'INFO'),
}
