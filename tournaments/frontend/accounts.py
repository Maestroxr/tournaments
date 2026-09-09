"""Website account authority. Email links never authenticate a game directly."""
import json
import logging
from datetime import timedelta
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import PasswordResetTokenGenerator, default_token_generator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.views.decorators.http import require_POST

from .forms import SignupForm
from .models import AccountEmail

logger = logging.getLogger(__name__)
SENT = {'detail': 'If the account is eligible, an email with the next step will arrive shortly.'}
INVALID = {'detail': 'This link is invalid or expired. Please request a new link.'}


class VerificationTokens(PasswordResetTokenGenerator):
    key_salt = 'frontend.accounts.verify_email'

    def _make_hash_value(self, user, timestamp):
        account = AccountEmail.objects.get(user=user)
        return f'{super()._make_hash_value(user, timestamp)}|{account.email}|{account.verified_at}'


verification_tokens = VerificationTokens()


class PublicSignupForm(SignupForm):
    email = forms.EmailField(max_length=254)
    phone_number = forms.CharField(max_length=24)

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if AccountEmail.objects.filter(email=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('This email cannot be used. Try signing in or recovering your account.')
        return email

    def clean_phone_number(self):
        from .forms import require_phone_number
        return require_phone_number(self.cleaned_data.get('phone_number'))


def body(request):
    try:
        data = json.loads(request.body or '{}')
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def send_link(account, purpose):
    now = timezone.now()
    # Database cooldown is shared by all processes, including resend and reset.
    with transaction.atomic():
        account = AccountEmail.objects.select_for_update().select_related('user').get(pk=account.pk)
        if account.last_sent_at and account.last_sent_at > now - timedelta(seconds=60):
            return
        account.last_sent_at = now
        account.save(update_fields=['last_sent_at'])
        generator = verification_tokens if purpose == 'verify' else default_token_generator
        query = urlencode({'uid': urlsafe_base64_encode(force_bytes(account.user_id)),
                           'token': generator.make_token(account.user)})
        url = f'{settings.ACCOUNT_FRONTEND_URL.rstrip("/")}/account/{purpose}#{query}'
    try:
        send_mail('Verify your account' if purpose == 'verify' else 'Reset your password',
                  f'Open this link to continue:\n{url}\n\nThis link expires in one hour and can be used once.\nIf you did not request it, ignore this email.',
                  settings.DEFAULT_FROM_EMAIL, [account.email], fail_silently=False)
    except Exception:
        logger.exception('account_email_delivery_failed purpose=%s account=%s', purpose, account.pk)
        # Permit another request after a mail transport failure.
        AccountEmail.objects.filter(pk=account.pk, last_sent_at=now).update(last_sent_at=None)


@require_POST
def signup(request):
    form = PublicSignupForm(body(request))
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=400)
    try:
        with transaction.atomic():
            user = form.save(commit=False)
            user.email = form.cleaned_data['email']
            user.is_active = False
            user.save()
            account = AccountEmail.objects.create(user=user, email=user.email)
            from tournaments import models
            models.UserContact.objects.create(user=user, phone_number=form.cleaned_data['phone_number'])
    except IntegrityError:
        return JsonResponse({'detail': 'This account already exists.'}, status=400)
    send_link(account, 'verify')
    return JsonResponse(SENT, status=201)


@require_POST
def request_link(request, purpose):
    email = body(request).get('email', '')
    if isinstance(email, str):
        account = AccountEmail.objects.select_related('user').filter(email=email.strip().lower()).first()
        if account and ((purpose == 'verify' and account.verified_at is None)
                        or (purpose == 'reset' and account.verified_at and account.user.is_active)):
            send_link(account, purpose)
    return JsonResponse(SENT)


@require_POST
def confirm_link(request, purpose):
    data = body(request)
    try:
        user_id = urlsafe_base64_decode(data.get('uid', '')).decode()
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user_id)
            account = AccountEmail.objects.select_for_update().get(user=user)
            generator = verification_tokens if purpose == 'verify' else default_token_generator
            if not generator.check_token(user, data.get('token')):
                return JsonResponse(INVALID, status=400)
            if purpose == 'verify':
                if account.verified_at is not None:
                    return JsonResponse(INVALID, status=400)
                account.verified_at = timezone.now()
                account.save(update_fields=['verified_at'])
                user.is_active = True
                user.save(update_fields=['is_active'])
            else:
                if not account.verified_at or not user.is_active:
                    return JsonResponse(INVALID, status=400)
                form = SetPasswordForm(user, data)
                if not form.is_valid():
                    return JsonResponse({'errors': form.errors}, status=400)
                form.save()  # Invalidates this token and all previous Django sessions.
    except (ValueError, TypeError, OverflowError, UnicodeDecodeError, User.DoesNotExist, AccountEmail.DoesNotExist):
        return JsonResponse(INVALID, status=400)
    return JsonResponse({'detail': 'Account verified. You can sign in.' if purpose == 'verify'
                         else 'Password updated. Sign in with your new password.'})
