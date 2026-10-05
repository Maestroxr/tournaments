"""Explicitly run focused tests against in-memory SQLite, never production data."""
import os
import sys

os.environ['DJANGO_SETTINGS_MODULE'] = 'tournaments.settings.development'
os.environ['GAMELINK_BACKGAMMON_URL'] = 'https://example.invalid'

from django.conf import settings

# Resolve settings, then override all database aliases before Django initializes apps.
settings.DATABASES = {'default': {
    'ENGINE': 'tournaments.db.backends.sqlite3',
    'NAME': ':memory:',
    'TEST': {'NAME': ':memory:'},
}}
settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

import django
django.setup()

from django.test.runner import DiscoverRunner

if __name__ == '__main__':
    failures = DiscoverRunner(verbosity=2, interactive=False).run_tests([
        'tournaments.test_stage_query_budget',
    ])
    sys.exit(bool(failures))
