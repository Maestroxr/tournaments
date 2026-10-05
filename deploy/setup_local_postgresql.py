"""Create an empty, loopback-only development database; never import SQLite data."""

import argparse
import getpass
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / '.env.postgresql.local'
CLUSTER = ROOT / '.local-postgresql'


def postgres_binary(name):
    configured = os.environ.get('TOURNAMENTS_PG_BIN')
    if configured:
        candidate = Path(configured) / name
        if candidate.is_file():
            return candidate
    installed = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'PostgreSQL'
    candidates = sorted(installed.glob(f'*/bin/{name}'), key=lambda path: int(path.parent.parent.name), reverse=True)
    if not candidates:
        raise RuntimeError(f'{name} not found; set TOURNAMENTS_PG_BIN to the installed PostgreSQL bin directory.')
    return candidates[0]


def start_isolated_server(port):
    """Use installed binaries, with a separate cluster and generated SCRAM password."""
    data = CLUSTER / 'data'
    password_file = CLUSTER / 'admin.password'
    if not (data / 'PG_VERSION').is_file():
        # Refuse to take over a port, or an incomplete/unrecognized cluster.
        if data.exists():
            raise RuntimeError('Local cluster directory already exists without PG_VERSION; inspect it before retrying.')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
        CLUSTER.mkdir(exist_ok=True)
        password_file.write_text(secrets.token_urlsafe(40) + '\n', encoding='utf-8')
        subprocess.run(
            [
                str(postgres_binary('initdb.exe')),
                '-D',
                str(data),
                '-U',
                'postgres',
                '--encoding=UTF8',
                '--locale=C',
                '--auth=scram-sha-256',
                f'--pwfile={password_file}',
            ],
            check=True,
        )
        with (data / 'postgresql.conf').open('a', encoding='utf-8') as output:
            output.write(f"\nlisten_addresses = '127.0.0.1'\nport = {port}\n")
            output.write('fsync = on\nsynchronous_commit = on\nfull_page_writes = on\n')
    pg_ctl = postgres_binary('pg_ctl.exe')
    status = subprocess.run([str(pg_ctl), '-D', str(data), 'status'], capture_output=True)
    if status.returncode:
        subprocess.run(
            [str(pg_ctl), '-D', str(data), '-l', str(CLUSTER / 'server.log'), '-w', 'start'],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            check=True,
        )
    return password_file.read_text(encoding='utf-8').strip()


def read_config():
    values = {}
    if CONFIG.is_file():
        for line in CONFIG.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int)
    parser.add_argument('--isolated', action='store_true', help='Create a project-owned local server on port 55432.')
    parser.add_argument('--start-only', action='store_true', help='Start the project server without changing schema.')
    parser.add_argument('--admin-user', default='postgres')
    parser.add_argument('--database', default='backgammon_tournaments_local')
    parser.add_argument('--role', default='backgammon_tournaments_local')
    args = parser.parse_args()
    config = read_config()
    args.port = args.port or (int(config.get('TOURNAMENTS_PG_PORT', '55432')) if args.isolated else 5432)
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    for name in (args.database, args.role):
        if not name.isascii() or len(name) > 63 or not name.replace('_', '').isalnum():
            parser.error('Database and role names must be ASCII letters, digits or underscores, up to 63 characters.')

    admin_password = start_isolated_server(args.port) if args.isolated else None
    if args.start_only:
        if not args.isolated:
            parser.error('--start-only requires --isolated.')
        print(f'Project PostgreSQL is running on 127.0.0.1:{args.port}.')
        return
    if config:
        expected = {
            'TOURNAMENTS_LOCAL_DATABASE': 'postgresql',
            'TOURNAMENTS_PG_HOST': '127.0.0.1',
            'TOURNAMENTS_PG_PORT': str(args.port),
            'TOURNAMENTS_PG_NAME': args.database,
            'TOURNAMENTS_PG_USER': args.role,
        }
        if any(config.get(key) != value for key, value in expected.items()):
            raise RuntimeError('Existing local database configuration differs; refusing to replace it.')
        password = config['TOURNAMENTS_PG_PASSWORD']
    else:
        if admin_password is None:
            admin_password = getpass.getpass(f'Local PostgreSQL password for {args.admin_user}: ')
        password = secrets.token_urlsafe(32)
        admin = psycopg2.connect(
            host='127.0.0.1',
            port=args.port,
            dbname='postgres',
            user=args.admin_user,
            password=admin_password,
            connect_timeout=5,
        )
        try:
            admin.autocommit = True
            with admin.cursor() as cursor:
                cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', (args.database,))
                if cursor.fetchone():
                    raise RuntimeError('Target database already exists; refusing to modify it.')
                cursor.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (args.role,))
                if cursor.fetchone():
                    raise RuntimeError('Target role already exists; refusing to change its credentials.')
                # CREATEDB is for Django test databases only. No superuser privileges.
                cursor.execute(
                    sql.SQL('CREATE ROLE {} LOGIN PASSWORD %s NOSUPERUSER CREATEDB NOCREATEROLE').format(
                        sql.Identifier(args.role)
                    ),
                    (password,),
                )
                # Save credentials before CREATE DATABASE, so a failed creation is recoverable.
                config = {
                    'TOURNAMENTS_LOCAL_DATABASE': 'postgresql',
                    'TOURNAMENTS_PG_HOST': '127.0.0.1',
                    'TOURNAMENTS_PG_PORT': str(args.port),
                    'TOURNAMENTS_PG_NAME': args.database,
                    'TOURNAMENTS_PG_USER': args.role,
                    'TOURNAMENTS_PG_PASSWORD': password,
                    'TOURNAMENTS_LOCAL_DEBUG': '1',
                    'TOURNAMENTS_LOCAL_SECRET_KEY': secrets.token_urlsafe(48),
                }
                CONFIG.write_text('\n'.join(f'{key}={value}' for key, value in config.items()) + '\n', encoding='utf-8')
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
                        sql.Identifier(args.database), sql.Identifier(args.role)
                    ),
                )
        finally:
            admin.close()

    connection = psycopg2.connect(
        host=config['TOURNAMENTS_PG_HOST'],
        port=args.port,
        dbname=args.database,
        user=args.role,
        password=password,
        connect_timeout=5,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_database(), current_user, version()')
            database, role, version = cursor.fetchone()
            print(f'Connected to local database {database} as {role}. {version.split(",")[0]}')
    finally:
        connection.close()

    # Explicit values prevent inherited settings or environment variables from
    # accidentally routing migration commands to a different database.
    environment = os.environ.copy()
    environment.update(config)
    environment['DJANGO_SETTINGS_MODULE'] = 'tournaments.settings.development'
    for arguments in (['migrate', '--noinput'], ['migrate', '--check']):
        subprocess.run(
            [sys.executable, str(ROOT / 'tournaments' / 'manage.py'), *arguments],
            cwd=ROOT / 'tournaments',
            env=environment,
            check=True,
        )
    print('Local PostgreSQL schema is ready. No SQLite data was imported. Restart local Django and workers.')


if __name__ == '__main__':
    main()
