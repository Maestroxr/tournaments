"""Check SMTP authentication without sending mail or exposing credentials."""
from smtplib import SMTPAuthenticationError, SMTPException

from django.conf import settings
from django.core.mail import get_connection
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Check account SMTP configuration and authentication without sending email.'

    def handle(self, *args, **options):
        if settings.EMAIL_BACKEND != 'django.core.mail.backends.smtp.EmailBackend':
            raise CommandError('EMAIL_BACKEND must use the SMTP backend for real delivery.')
        required = ('EMAIL_HOST', 'EMAIL_HOST_USER', 'EMAIL_HOST_PASSWORD', 'DEFAULT_FROM_EMAIL')
        missing = [name for name in required if not getattr(settings, name, '')]
        if missing:
            raise CommandError('Fill in these settings in .env: ' + ', '.join(missing))
        try:
            with get_connection() as connection:
                if connection.connection is None:
                    raise CommandError('The SMTP connection could not be opened.')
        except SMTPAuthenticationError:
            raise CommandError('SMTP authentication failed. Check the Gmail address and Google App Password in .env.') from None
        except (SMTPException, OSError):
            raise CommandError('SMTP connection failed. Check the host, port, TLS settings and network access.') from None
        self.stdout.write(self.style.SUCCESS('SMTP connection and authentication succeeded. No email was sent.'))
        self.stdout.write('Restart the running Django server after changing .env, then test password reset delivery.')
