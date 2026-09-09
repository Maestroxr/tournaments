from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tournaments.models import Tournament, Fixture


class TournamentCreationTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='organizer', is_staff=True)
        self.client.force_login(self.staff)
        self.payload = {'name': 'Club tournament', 'template': 'knockout',
                        'min_players': 2, 'max_players': 8, 'open_registration': True}

    def create(self, payload=None):
        return self.client.post(reverse('api-admin-tournaments'),
                                data=payload or self.payload, content_type='application/json')

    def test_create_opens_registration_without_starting_matches(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        tournament = Tournament.objects.get(pk=response.json()['id'])
        self.assertTrue(tournament.published)
        self.assertEqual(tournament.state, 'open')
        self.assertEqual(response.json()['state'], 'open')
        self.assertIsNone(tournament.starts_at)
        self.assertIsNotNone(tournament.created_at)
        self.assertLessEqual(tournament.created_at, timezone.now())
        self.assertEqual(response.json()['created_at'], tournament.created_at.isoformat())
        self.assertFalse(Fixture.objects.filter(mode__tournament=tournament).exists())

    def test_legacy_create_remains_a_draft(self):
        self.payload.pop('open_registration')
        response = self.create()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['state'], 'draft')

    def test_nonstaff_cannot_publish(self):
        user = User.objects.create_user(username='player')
        self.client.force_login(user)
        self.assertEqual(self.create().status_code, 403)
        self.assertFalse(Tournament.objects.exists())

    def test_failed_metadata_save_rolls_back_creation(self):
        original_save = Tournament.save

        def fail_final_save(instance, *args, **kwargs):
            if 'published' in (kwargs.get('update_fields') or []):
                raise RuntimeError('Simulated save failure')
            return original_save(instance, *args, **kwargs)

        with patch.object(Tournament, 'save', fail_final_save):
            with self.assertRaisesMessage(RuntimeError, 'Simulated save failure'):
                self.create()
        self.assertFalse(Tournament.objects.exists())
