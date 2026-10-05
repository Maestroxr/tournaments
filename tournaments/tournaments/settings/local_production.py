"""Local PostgreSQL with production HTTP safeguards; requires a real HTTPS setup."""

from django.core.exceptions import ImproperlyConfigured

from tournaments.settings.development import *

if DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise ImproperlyConfigured('local_production requires the local PostgreSQL configuration.')
if not os.environ.get('TOURNAMENTS_LOCAL_SECRET_KEY'):
    raise ImproperlyConfigured('local_production requires a generated local SECRET_KEY.')

DEBUG = False
ACCOUNT_FRONTEND_URL = os.environ.get('TOURNAMENTS_LOCAL_FRONTEND_URL', ACCOUNT_FRONTEND_URL)
GAMELINK_BACKGAMMON_URL = os.environ.get('TOURNAMENTS_LOCAL_GAME_URL', GAMELINK_BACKGAMMON_URL)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_CONTENT_TYPE_NOSNIFF = True
