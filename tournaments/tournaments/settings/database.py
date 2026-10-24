"""PostgreSQL configuration shared by the active settings profiles."""
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


def postgresql_database(environ, *, prefix='DB', required=False, loopback_only=False, require_host=False):
    # The club uses named variables, not DATABASE_URL, but never silently accept
    # an obsolete SQLite URL inherited from an old local launcher.
    url = environ.get('DATABASE_URL', '').strip()
    try:
        valid_scheme = not url or urlsplit(url).scheme.lower() in ('postgres', 'postgresql', 'pgsql')
    except ValueError:
        valid_scheme = False
    if not valid_scheme:
        raise ImproperlyConfigured('PostgreSQL is required; SQLite and other DATABASE_URL schemes are unsupported.')
    needed = ['NAME', 'USER', 'PASSWORD'] + (['HOST'] if require_host else [])
    missing = [f'{prefix}_{name}' for name in needed if not environ.get(f'{prefix}_{name}')]
    if required and missing:
        raise ImproperlyConfigured('PostgreSQL configuration requires: ' + ', '.join(missing) + '.')
    host = environ.get(f'{prefix}_HOST', '127.0.0.1')
    if loopback_only and host not in ('127.0.0.1', 'localhost', '::1'):
        raise ImproperlyConfigured('The local PostgreSQL profile only accepts loopback hosts.')
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': environ.get(f'{prefix}_NAME', ''),
        'USER': environ.get(f'{prefix}_USER', ''),
        'PASSWORD': environ.get(f'{prefix}_PASSWORD', ''),
        'HOST': host,
        'PORT': environ.get(f'{prefix}_PORT', '5432'),
        'CONN_MAX_AGE': 0,
        'OPTIONS': {'connect_timeout': 5},
    }


def local_postgresql_database(environ):
    if environ.get('TOURNAMENTS_LOCAL_DATABASE', 'postgresql').strip().lower() != 'postgresql':
        raise ImproperlyConfigured('TOURNAMENTS_LOCAL_DATABASE must be postgresql; SQLite is unsupported.')
    # A partial legacy profile fails rather than mixing credentials from two
    # different databases. The PG_BIN installation hint is not a connection.
    legacy_keys = (f'TOURNAMENTS_PG_{name}' for name in ('NAME', 'USER', 'PASSWORD', 'HOST', 'PORT'))
    prefix = 'TOURNAMENTS_PG' if any(key in environ for key in legacy_keys) else 'DB'
    return postgresql_database(environ, prefix=prefix, required=True, loopback_only=True)
