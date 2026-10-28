"""Authenticated account changes that require the current password."""

import json

from django.contrib.auth import logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

PASSWORD_FIELDS = ('old_password', 'new_password1', 'new_password2')
MAX_PASSWORD_LENGTH = 4096


def _authentication_required(request):
    logout(request)
    return JsonResponse({'code': 'authentication_required'}, status=401)


@never_cache
@require_POST
@csrf_protect
def change_password(request):
    if not request.user.is_authenticated:
        return JsonResponse({'code': 'authentication_required'}, status=401)
    authenticated_password = request.user.password
    try:
        data = json.loads(request.body or '{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'code': 'invalid_payload'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'code': 'invalid_payload'}, status=400)

    errors = {}
    for field in PASSWORD_FIELDS:
        value = data.get(field, '')
        if not isinstance(value, str):
            errors[field] = [{'code': 'invalid_type'}]
        elif len(value) > MAX_PASSWORD_LENGTH:
            errors[field] = [{'code': 'max_length'}]
    if errors:
        return JsonResponse({'errors': errors}, status=400)

    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=request.user.pk).first()
        # Authentication may have happened before another request changed the
        # password. Recheck the current row after acquiring its lock.
        if user is None or not user.is_active or not constant_time_compare(user.password, authenticated_password):
            return _authentication_required(request)
        if not user.has_usable_password():
            return JsonResponse({'code': 'password_unavailable'}, status=409)
        form = PasswordChangeForm(user, {field: data.get(field, '') for field in PASSWORD_FIELDS})
        if not form.is_valid():
            return JsonResponse({
                'errors': {
                    field: [{'code': error.code or 'invalid'} for error in field_errors]
                    for field, field_errors in form.errors.as_data().items()
                },
            }, status=400)
        form.save()

    update_session_auth_hash(request, user)
    return JsonResponse({'status': 'password_changed'})
