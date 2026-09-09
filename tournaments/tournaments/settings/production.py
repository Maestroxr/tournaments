import os

from tournaments.settings.common import *

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ['SECRET_KEY']

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = [
    os.environ['HOSTNAME'],
]

CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

STATIC_ROOT = BASE_DIR / '../deployed'

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
