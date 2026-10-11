"""Regression coverage for independent game policies and scoped admin writes."""
from copy import deepcopy
from importlib import import_module
import json

from django.apps import apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase

from frontend.game_formats import quote
from tournaments.models import DirectPlaySettings, WalletTransaction


class GameModeSettingsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('settings-admin', is_staff=True)
        self.client.force_login(self.admin)
        self.settings = DirectPlaySettings.load()

    def save_section(self, section, **fields):
        return self.client.put('/api/admin/direct-play/settings',
            json.dumps({'section': section, **fields}), content_type='application/json')

    def test_friend_clocks_are_independent_from_disabled_public_match(self):
        row = self.settings
        row.format_profiles['match'].update(enabled=False, private=False, time_controls=['fast'])
        row.friend_rules = {'enabled': True, 'target_points': [5],
                            'time_controls': ['none'], 'doubling_options': [True, False]}
        row.save()
        name, profile, stakes, points, clock, _ = quote(row, {
            'game_format': 'match', 'mode': 'friend', 'target_points': 5,
            'time_control': 'none', 'doubling_enabled': True}, False)
        self.assertEqual((name, points, clock), ('match', 5, 'none'))
        self.assertTrue(profile['friend_fee_only'])
        self.assertEqual(str(stakes[0]), '250.00')
        WalletTransaction.create_entry(user=self.admin, amount=1000, kind='deposit')
        response = self.client.post('/api/head-to-head/tables', {
            'game_format': 'match', 'mode': 'friend', 'target_points': 5,
            'time_control': 'none', 'doubling_enabled': True}, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['time_control'], 'none')

    def test_friend_section_does_not_change_match_or_money_or_legacy(self):
        profiles = deepcopy(self.settings.format_profiles)
        legacy = deepcopy(self.settings.game_rules)
        rules = {'enabled': True, 'target_points': [1, 5],
                 'time_controls': ['none'], 'doubling_options': [True, False]}
        response = self.save_section('friend', friend_rules=rules, friend_game_fee=75)
        self.assertEqual(response.status_code, 200)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.friend_rules, {**rules, 'max_cube': 64})
        self.assertEqual(self.settings.format_profiles, profiles)
        self.assertEqual(self.settings.game_rules, legacy)
        self.assertEqual(self.settings.friend_fee_for(5), 375)

    def test_match_profile_patch_keeps_other_profile_fields_and_friend_policy(self):
        self.settings.friend_rules = {'enabled': True, 'target_points': [1, 5],
                                     'time_controls': ['none'], 'doubling_options': [False]}
        self.settings.save()
        money = deepcopy(self.settings.format_profiles['money'])
        friend = deepcopy(self.settings.friend_rules)
        old = deepcopy(self.settings.format_profiles['match'])
        response = self.save_section('match', profile={'time_controls': ['fast']})
        self.assertEqual(response.status_code, 200)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.format_profiles['match'], {**old, 'time_controls': ['fast']})
        self.assertEqual(self.settings.format_profiles['money'], money)
        self.assertEqual(self.settings.friend_rules, friend)
        with self.assertRaises(ValidationError):
            quote(self.settings, {'game_format': 'match', 'mode': 'match', 'amount': 100,
                'target_points': 5, 'time_control': 'none', 'doubling_enabled': True}, False)

    def test_match_cube_limit_does_not_change_friend_cube_limit(self):
        rules = {'enabled': True, 'target_points': [5], 'time_controls': ['none'],
                 'doubling_options': [True, False], 'max_cube': 4}
        self.assertEqual(self.save_section('friend', friend_rules=rules).status_code, 200)
        self.assertEqual(self.save_section('match', profile={'max_cube': 32}).status_code, 200)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.friend_profile()['max_cube'], 4)
        self.assertEqual(self.settings.format_profiles['match']['max_cube'], 32)

    def test_money_clock_is_fixed_and_ignores_client_clock_and_legacy_list_order(self):
        response = self.save_section('money', money_time_control='none')
        self.assertEqual(response.status_code, 200)
        self.settings.refresh_from_db()
        self.settings.format_profiles['money']['time_controls'] = ['slow', 'normal']
        result = quote(self.settings, {'game_format': 'money', 'amounts': [100],
                                      'time_control': 'slow'}, True)
        self.assertEqual(result[4], 'none')

    def test_invalid_policy_rolls_back_price_and_reports_field(self):
        response = self.save_section('friend', friend_game_fee=99, friend_rules={
            'enabled': True, 'target_points': [5], 'time_controls': [], 'doubling_options': [False]})
        self.assertEqual(response.status_code, 400)
        self.assertIn('friend_rules', response.json()['errors'])
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.friend_game_fee, 50)
        self.assertEqual(self.settings.friend_rules['time_controls'], ['none', 'normal', 'fast', 'slow'])

    def test_sections_reject_cross_section_fields_and_inactive_money_controls(self):
        for payload in ({'friend_game_fee': 99}, {'profile': {'private': False}},
                        {'profile': {'max_cube': 2}}, {'profile': {'loss_limit_multiplier': 2}}):
            self.assertEqual(self.save_section('money', **payload).status_code, 400)
        self.assertEqual(self.save_section('friend', enabled=False).status_code, 400)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.friend_game_fee, 50)

    def test_scoped_saving_requires_staff_and_nonempty_practice_policy(self):
        response = self.save_section('practice', practice_rules={'target_points': [2], 'time_controls': ['none']})
        self.assertEqual(response.status_code, 400)
        self.assertIn('practice_rules', response.json()['errors'])
        self.admin.is_staff = False
        self.admin.save()
        self.assertEqual(self.save_section('money', money_time_control='none').status_code, 403)

    def test_data_migration_copies_existing_rules_and_current_money_clock(self):
        profile = self.settings.format_profiles['match']
        profile.update(private=False, max_cube=8, target_points=[2, 7], time_controls=['slow', 'none'], doubling_options=[False])
        self.settings.format_profiles['money']['time_controls'] = ['fast', 'none']
        self.settings.save()
        original = deepcopy(self.settings.format_profiles)
        migration = import_module('tournaments.migrations.0035_game_mode_settings')
        migration.preserve_current_rules(apps, connection.schema_editor())
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.friend_rules, {'enabled': False, 'target_points': [2, 7],
            'time_controls': ['slow', 'none'], 'doubling_options': [False], 'max_cube': 8})
        self.assertEqual(self.settings.money_time_control, 'fast')
        self.assertEqual(self.settings.format_profiles, original)
