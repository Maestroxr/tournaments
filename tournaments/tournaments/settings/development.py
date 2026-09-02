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
    'http://127.0.0.1:5173',
    'http://127.0.0.1:5174',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://*.nip.io',
] + env_list('CSRF_TRUSTED_ORIGINS')
# For dev via Vite proxy /api -> Django, ensure CSRF cookie is readable by JS
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'
