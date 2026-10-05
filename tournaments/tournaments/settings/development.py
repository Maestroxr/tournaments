from tournaments.settings.common import *

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-ouqc8j0sk$gn+*9zja*ii=rs=$q()cs$e*9$fg1(y28d#m8m$d'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:5173',
    'http://localhost:5174',
    'http://localhost:5175',
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
    'http://127.0.0.1:5175',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://*.nip.io',
] + env_list('CSRF_TRUSTED_ORIGINS')
# For dev via Vite proxy /api -> Django, ensure CSRF cookie is readable by JS
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'

# Only development loads this private, machine-specific database configuration.
# Production continues to use its explicitly configured database.
load_local_env(BASE_DIR.parent / '.env.postgresql.local')
_local_database = os.environ.get('TOURNAMENTS_LOCAL_DATABASE', 'sqlite')
if _local_database == 'postgresql':
    from django.core.exceptions import ImproperlyConfigured

    _required_database_vars = (
        'TOURNAMENTS_PG_NAME', 'TOURNAMENTS_PG_USER', 'TOURNAMENTS_PG_PASSWORD',
    )
    if any(not os.environ.get(name) for name in _required_database_vars):
        raise ImproperlyConfigured('Local PostgreSQL requires NAME, USER and PASSWORD in .env.postgresql.local.')
    _database_host = os.environ.get('TOURNAMENTS_PG_HOST', '127.0.0.1')
    if _database_host not in ('127.0.0.1', 'localhost', '::1'):
        raise ImproperlyConfigured('The local PostgreSQL profile only accepts loopback hosts.')
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ['TOURNAMENTS_PG_NAME'],
            'USER': os.environ['TOURNAMENTS_PG_USER'],
            'PASSWORD': os.environ['TOURNAMENTS_PG_PASSWORD'],
            'HOST': _database_host,
            'PORT': os.environ.get('TOURNAMENTS_PG_PORT', '5432'),
            'CONN_MAX_AGE': 0,
            'OPTIONS': {'connect_timeout': 5},
        },
    }
    DEBUG = os.environ.get('TOURNAMENTS_LOCAL_DEBUG', '1') == '1'
    SECRET_KEY = os.environ.get('TOURNAMENTS_LOCAL_SECRET_KEY', SECRET_KEY)
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]'] + env_list('TOURNAMENTS_LOCAL_ALLOWED_HOSTS')
elif _local_database != 'sqlite':
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured('TOURNAMENTS_LOCAL_DATABASE must be sqlite or postgresql.')
