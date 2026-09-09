import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Generate server-only Web Push settings into a new private file; never overwrite existing keys.'

    def add_arguments(self, parser):
        parser.add_argument('--subject', required=True, help='A mailto: contact address for the site operator.')
        parser.add_argument('--output', default='.env.webpush')

    def handle(self, *args, **options):
        subject = options['subject']
        if not subject.startswith('mailto:') or '@' not in subject or any(char.isspace() for char in subject):
            raise CommandError('Use a valid mailto: contact address.')
        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
        output = Path(options['output']).resolve()
        try:
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as error:
            raise CommandError(f'Cannot create key file: {error}') from error
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(f'WEB_PUSH_PUBLIC_KEY={encode(public)}\nWEB_PUSH_PRIVATE_KEY={encode(private)}\nWEB_PUSH_SUBJECT={subject}\n')
        self.stdout.write(f'Created {output}. Load these settings only on the tournaments server; do not commit the file.')
