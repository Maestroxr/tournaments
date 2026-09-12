"""Google Identity Services: Django CSRF + session nonce, no automatic email linking."""
import secrets
import time
import logging

from django import forms
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .accounts import body, send_link
from .forms import require_phone_number, validate_admin_username
from .models import AccountEmail, GoogleIdentity

TTL = 600
logger = logging.getLogger(__name__)


def verify_credential(credential):
    # Import lazily so installations without Google enabled can still start.
    from google.auth.transport.requests import Request
    from google.auth.exceptions import GoogleAuthError, TransportError
    from google.oauth2.id_token import verify_oauth2_token
    try:
        return verify_oauth2_token(credential, Request(), settings.GOOGLE_CLIENT_ID)
    except TransportError:
        raise
    except GoogleAuthError as error:
        raise ValueError('Invalid Google credential') from error


def failure(code, status=400):
    logger.info('google_auth_rejected code=%s', code)
    return JsonResponse({'code': code}, status=status)


@never_cache
@require_POST
def config(request):
    client_id = getattr(settings, 'GOOGLE_CLIENT_ID', '')
    if not client_id:
        return JsonResponse({'enabled': False})
    nonce = secrets.token_urlsafe(32)
    # Each open tab owns its challenge; opening another page must not invalidate it.
    now = time.time()
    challenges = [item for item in request.session.get('google_challenges', []) if now - item['issued'] <= TTL]
    request.session['google_challenges'] = challenges[-7:] + [{'value': nonce, 'issued': now}]
    return JsonResponse({'enabled': True, 'client_id': client_id, 'nonce': nonce})


def sign_in(request, user):
    if not user.is_active:
        return failure('account_unavailable', 403)
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    return JsonResponse({'status': 'authenticated'})


@never_cache
@require_POST
def authenticate(request):
    if not getattr(settings, 'GOOGLE_CLIENT_ID', ''):
        return failure('unavailable', 503)
    request.session.pop('google_pending', None)
    challenges = [item for item in request.session.get('google_challenges', []) if time.time() - item['issued'] <= TTL]
    credential = body(request).get('credential')
    if not challenges or not isinstance(credential, str) or len(credential) > 16384:
        return failure('expired')
    try:
        claims = verify_credential(credential)
    except ValueError:
        logger.warning('google_auth_verification_failed category=invalid_token')
        return failure('invalid_credential', 401)
    except Exception as error:
        # Never include credential or provider exception contents in logs/responses.
        logger.warning('google_auth_verification_failed category=%s', type(error).__name__)
        return failure('unavailable', 503)
    nonce = claims.get('nonce')
    challenge = next((item for item in challenges if isinstance(nonce, str) and secrets.compare_digest(nonce.encode(), item['value'].encode())), None)
    if challenge is None:
        return failure('challenge_mismatch', 401)
    request.session['google_challenges'] = [item for item in challenges if item != challenge]
    subject = claims.get('sub')
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        return failure('invalid_credential', 401)
    identity = GoogleIdentity.objects.select_related('user').filter(subject=subject).first()
    if identity:
        return sign_in(request, identity.user)
    try:
        email = forms.EmailField(max_length=254).clean(claims.get('email')).lower()
    except forms.ValidationError:
        return failure('invalid_credential', 401)
    if claims.get('email_verified') is not True:
        return failure('invalid_credential', 401)
    if AccountEmail.objects.filter(email__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
        return failure('existing_account', 409)
    authoritative = email.endswith('@gmail.com') or bool(claims.get('hd'))
    request.session['google_pending'] = {'subject': subject, 'email': email, 'verified': authoritative, 'issued': time.time()}
    return JsonResponse({'status': 'profile_required', 'email': email})


class ProfileForm(forms.ModelForm):
    phone_number = forms.CharField(max_length=24)
    password = forms.CharField(strip=False, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ['username']

    def clean_username(self):
        name = self.cleaned_data['username']
        validate_admin_username(name)
        name = name[:1].upper() + name[1:]
        if User.objects.filter(username__iexact=name).exists():
            raise forms.ValidationError('This username is already taken.')
        if name.lower().startswith('testuser-'):
            raise forms.ValidationError('This username is reserved.')
        return name

    def clean_phone_number(self):
        return require_phone_number(self.cleaned_data['phone_number'])

    def _post_clean(self):
        super()._post_clean()
        password = self.cleaned_data.get('password')
        if password:
            try:
                validate_password(password, self.instance)
            except forms.ValidationError as error:
                self.add_error('password', error)


@never_cache
@require_POST
def complete(request):
    if not getattr(settings, 'GOOGLE_CLIENT_ID', ''):
        return failure('unavailable', 503)
    pending = request.session.get('google_pending')
    if not pending or time.time() - pending['issued'] > TTL:
        request.session.pop('google_pending', None)
        return failure('expired')
    form = ProfileForm(body(request), instance=User(email=pending['email']))
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=400)
    try:
        with transaction.atomic():
            if User.objects.filter(email__iexact=pending['email']).exists():
                return failure('existing_account', 409)
            user = form.save(commit=False)
            user.email = pending['email']
            user.is_active = pending['verified']
            user.set_password(form.cleaned_data['password'])
            user.save()
            account = AccountEmail.objects.create(user=user, email=user.email, verified_at=timezone.now() if pending['verified'] else None)
            GoogleIdentity.objects.create(user=user, subject=pending['subject'])
            from tournaments.models import UserContact
            UserContact.objects.create(user=user, phone_number=form.cleaned_data['phone_number'])
    except IntegrityError:
        return failure('existing_account', 409)
    request.session.pop('google_pending', None)
    if not user.is_active:
        send_link(account, 'verify')
        return JsonResponse({'status': 'verification_required'})
    return sign_in(request, user)
