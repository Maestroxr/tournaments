from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from tournaments.settings.database import local_postgresql_database, postgresql_database


class PostgreSQLConfigurationTests(SimpleTestCase):
    def connection(self, **changes):
        return {'DB_NAME': 'club_test', 'DB_USER': 'club_test', 'DB_PASSWORD': 'config-test-password',
                'DB_HOST': '127.0.0.1', 'DB_PORT': '5432', **changes}

    def test_common_defaults_are_postgresql_without_requiring_development_credentials_early(self):
        database = postgresql_database({})
        self.assertEqual(database['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(database['NAME'], '')
        with self.assertRaisesMessage(ImproperlyConfigured, 'DB_NAME, DB_USER, DB_PASSWORD'):
            local_postgresql_database({})

    def test_existing_legacy_local_profile_keeps_its_database_and_port(self):
        environ = self.connection()
        environ.update(TOURNAMENTS_LOCAL_DATABASE='postgresql', TOURNAMENTS_PG_NAME='existing_club_local',
                       TOURNAMENTS_PG_USER='existing_club_login', TOURNAMENTS_PG_PASSWORD='local-test-password',
                       TOURNAMENTS_PG_HOST='127.0.0.1', TOURNAMENTS_PG_PORT='55432')
        database = local_postgresql_database(environ)
        self.assertEqual(database['NAME'], 'existing_club_local')
        self.assertEqual(database['USER'], 'existing_club_login')
        self.assertEqual(database['PORT'], '55432')
        with self.assertRaisesMessage(ImproperlyConfigured, 'TOURNAMENTS_PG_PASSWORD'):
            del environ['TOURNAMENTS_PG_PASSWORD']
            local_postgresql_database(environ)

    def test_named_variables_work_locally_and_docker_requires_explicit_host(self):
        environ = self.connection(TOURNAMENTS_PG_BIN='C:/PostgreSQL/bin')
        self.assertEqual(local_postgresql_database(environ)['NAME'], 'club_test')
        self.assertEqual(postgresql_database(environ, required=True, require_host=True)['ENGINE'],
                         'django.db.backends.postgresql')
        del environ['DB_HOST']
        with self.assertRaisesMessage(ImproperlyConfigured, 'DB_HOST'):
            postgresql_database(environ, required=True, require_host=True)

    def test_sqlite_opt_in_urls_and_remote_local_hosts_are_rejected(self):
        for changes in ({'TOURNAMENTS_LOCAL_DATABASE': 'sqlite'}, {'DATABASE_URL': 'sqlite:///ignored.sqlite3'},
                        {'DATABASE_URL': 'mysql://user:config-test-password@localhost/db'}, {'DB_HOST': 'remote.example'}):
            with self.subTest(changes=list(changes)), self.assertRaises(ImproperlyConfigured) as raised:
                local_postgresql_database(self.connection(**changes))
            self.assertNotIn('config-test-password', str(raised.exception))
