import re

import yaml
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth.models import User

from tournaments import models


def validate_admin_username(value):
    if not re.fullmatch(r'[A-Za-z0-9]+', value or ''):
        raise ValidationError('Use English letters and numbers only.')
    return value


def validate_phone_number(value):
    phone_number = (value or '').strip()
    if not phone_number:
        return ''
    digit_count = len(re.sub(r'\D', '', phone_number))
    if not re.fullmatch(r'\+?[0-9 ()-]+', phone_number) or not 7 <= digit_count <= 15:
        raise ValidationError('Enter a valid phone number.')
    return phone_number


class AdminUserCreateForm(UserCreationForm):
    is_staff = forms.BooleanField(required=False, label='Staff (admin access)')
    phone_number = forms.CharField(required=False, max_length=24)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'phone_number', 'password1', 'password2', 'is_staff')

    def clean_username(self):
        ret = super().clean_username()
        validate_admin_username(ret)
        if re.match(r'^testuser-[0-9]+$', self.cleaned_data.get('username')):
            raise ValidationError('This username is reserved.')
        return ret

    def clean_phone_number(self):
        return validate_phone_number(self.cleaned_data.get('phone_number'))

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            models.UserContact.objects.update_or_create(
                user=user,
                defaults={'phone_number': self.cleaned_data.get('phone_number', '')},
            )
        return user


class AdminUserUpdateForm(forms.ModelForm):
    is_staff = forms.BooleanField(required=False)
    phone_number = forms.CharField(required=False, max_length=24)
    new_password = forms.CharField(
        required=False, widget=forms.PasswordInput, label='New password (leave blank to keep)')

    class Meta:
        model = User
        fields = ('username', 'phone_number', 'is_staff', 'is_active')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            contact = models.UserContact.objects.filter(user=self.instance).first()
            self.fields['phone_number'].initial = contact.phone_number if contact else ''

    def clean_username(self):
        username = self.cleaned_data.get('username')
        validate_admin_username(username)
        if re.match(r'^testuser-[0-9]+$', username):
            raise ValidationError('This username is reserved.')
        return username

    def clean_phone_number(self):
        return validate_phone_number(self.cleaned_data.get('phone_number'))

    def save(self, commit=True):
        user = super().save(commit=False)
        pwd = self.cleaned_data.get('new_password')
        if pwd:
            user.set_password(pwd)
        if commit:
            user.save()
            models.UserContact.objects.update_or_create(
                user=user,
                defaults={'phone_number': self.cleaned_data.get('phone_number', '')},
            )
        return user


class SignupForm(UserCreationForm):

    def clean_username(self):
        username = self.cleaned_data.get('username', '')
        self.cleaned_data['username'] = username[:1].upper() + username[1:]
        ret = super(SignupForm, self).clean_username()
        if ret and re.match(r'^testuser-[0-9]+$', ret, re.IGNORECASE):
            raise ValidationError('This username is reserved.')
        return ret


class CreateTournamentForm(forms.Form):

    name = forms.CharField(label='Name', max_length=100, required=True)
    definition = forms.CharField(label='Definition', widget=forms.Textarea(
        attrs={'class': 'textarea-monospace'}), required=True)

    @transaction.atomic
    def validate_definition(self, definition):
        try:
            tournament = models.Tournament.load(
                definition=definition, name='Test')
            tournament.full_clean()
            for stage in tournament.stages.all():
                stage.full_clean()
        except ValidationError as error:
            raise ValidationError(' '.join((str(err)
                                  for err in error.messages))) from error
        except KeyError as error:
            raise ValidationError(
                f'Missing key: "{error.args[0]}".') from error
        except Exception as error:
            raise ValidationError(error) from error
        transaction.set_rollback(True)

    def clean_definition(self):
        definition_str = self.cleaned_data['definition']

        # Check for syntactic correctness.
        try:
            definition = yaml.safe_load(definition_str)
            assert isinstance(definition, dict)
        except (yaml.YAMLError, AssertionError) as error:
            raise ValidationError(
                'Definition must be supplied in valid YAML.') from error

        # Check for semantic correctness.
        self.validate_definition(definition)

        return definition

    def create_tournament(self, request):
        tournament = models.Tournament.load(
            definition=self.cleaned_data['definition'],
            name=self.cleaned_data['name'],
            creator=request.user)
        tournament.definition = self.data['definition']
        tournament.save()
        return tournament


class UpdateTournamentForm(CreateTournamentForm):

    def update_tournament(self, request, tournament):
        tournament.delete()
        return self.create_tournament(request)
