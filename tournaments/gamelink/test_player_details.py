import json
import time
import uuid
from decimal import Decimal

from django.test import RequestFactory

from gamelink import tests as link_tests
from gamelink.player_details import player_details
from gamelink.signing import sign_result_body
from tournaments.models import HeadToHeadTable, PlayerRating, WalletTransaction


@link_tests.gamelink_settings
class GamePlayerDetailsTests(link_tests.GameLinkTestBase):
    def request(self, *, signature=True, **changes):
        body = {'v': 1, 'purpose': 'game_player_details', 'iss': 'backgammon',
                'fixture_id': self.fixture.pk, 'tournament_id': self.tournament.pk,
                'room_id': str(uuid.uuid4())}
        body.update(changes)
        raw = json.dumps(body).encode()
        timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
        return RequestFactory().post('/api/gamelink/player-details/', raw, content_type='application/json',
            HTTP_X_GAMELINK_ISSUER='backgammon', HTTP_X_GAMELINK_TIMESTAMP=timestamp,
            HTTP_X_GAMELINK_NONCE=nonce,
            HTTP_X_GAMELINK_SIGNATURE=sign_result_body(raw, timestamp, nonce) if signature else 'invalid')

    def test_signed_fixture_reads_canonical_accounts_without_writing(self):
        PlayerRating.objects.update_or_create(user=self.users[0], defaults={'value': 1562})
        WalletTransaction.create_entry(user=self.users[0], amount='65800', kind=WalletTransaction.KIND_DEPOSIT)
        count = WalletTransaction.objects.count()
        response = player_details(self.request())
        self.assertEqual(response.status_code, 200)
        players = json.loads(response.content)['players']
        self.assertEqual(players['p1']['rating'], 1562)
        self.assertEqual(Decimal(players['p1']['balance']), Decimal('65800'))
        self.assertEqual(players['p2']['rating'], 1000)
        self.assertEqual(WalletTransaction.objects.count(), count)
        self.assertFalse(PlayerRating.objects.filter(user=self.users[1]).exists())

    def test_unsigned_request_rejected_before_account_reads(self):
        self.assertEqual(player_details(self.request(signature=False)).status_code, 401)

    def test_room_mismatch_refuses_participant_data(self):
        self.game_link.external_room_id = str(uuid.uuid4())
        self.game_link.save(update_fields=['external_room_id'])
        self.assertEqual(player_details(self.request()).status_code, 404)

    def test_direct_table_maps_host_and_guest(self):
        table = HeadToHeadTable.objects.create(code='DETAIL', mode='match', host=self.users[1], guest=self.users[0],
            amount=100, fee_percent=0, fee_per_player=0)
        PlayerRating.objects.update_or_create(user=self.users[1], defaults={'value': 1063})
        response = player_details(self.request(fixture_id=-table.pk, tournament_id=0))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['players']['p1']['rating'], 1063)
