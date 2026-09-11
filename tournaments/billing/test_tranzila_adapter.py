import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, override_settings

from .tranzila import ProviderError, Tranzila


@override_settings(TRANZILA_ENABLED=True, TRANZILA_ENVIRONMENT='test',
                   TRANZILA_TERMINAL='testterminal', TRANZILA_APP_KEY='app-key',
                   TRANZILA_APP_SECRET='private-secret',
                   TRANZILA_RETURN_URL='https://example.com/payment-return',
                   TRANZILA_NOTIFY_URL='https://example.com/payment-notify')
class TranzilaAdapterTests(SimpleTestCase):
    def response(self, data, status=200):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.iter_content.return_value = [json.dumps(data).encode()]
        return response

    @patch('billing.tranzila.requests.post')
    @patch('billing.tranzila.secrets.token_hex', return_value='ab' * 40)
    @patch('billing.tranzila.time.time', return_value=1700000000)
    def test_handshake_hmac_exact_amount_and_safe_post(self, clock, nonce, post):
        post.return_value = self.response({'error_code': 0, 'thtk': 'token123'})
        result = Tranzila().handshake('checkout-123', Decimal('10.10'), 'ILS')
        args, kwargs = post.call_args
        self.assertEqual(args[0], Tranzila.HANDSHAKE_URL)
        self.assertIn(b'"sum":10.10', kwargs['data'])
        self.assertEqual(json.loads(kwargs['data'])['request_params'], {'checkout_id': 'checkout-123'})
        expected = hmac.new(('private-secret1700000000' + 'ab' * 40).encode(),
                            b'app-key', hashlib.sha256).hexdigest()
        self.assertEqual(kwargs['headers']['X-tranzila-api-access-token'], expected)
        self.assertEqual(kwargs['timeout'], (5, 20))
        self.assertTrue(kwargs['verify'])
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(result['method'], 'POST')
        self.assertEqual(result['fields']['sum'], '10.10')
        self.assertEqual(result['fields']['currency'], '1')
        self.assertEqual(result['fields']['DCdisable'], 'checkout-123')
        self.assertNotIn('private-secret', json.dumps(result))
        self.assertNotIn('app-key', json.dumps(result))

    @patch('billing.tranzila.requests.post')
    def test_fail_closed_configuration_and_invalid_amounts(self, post):
        for config in ({'TRANZILA_ENABLED': False}, {'TRANZILA_TERMINAL': '../evil'},
                       {'TRANZILA_APP_SECRET': ''}, {'TRANZILA_ENVIRONMENT': 'sandbox'},
                       {'TRANZILA_RETURN_URL': 'http://example.com'},
                       {'TRANZILA_NOTIFY_URL': 'https://user:pass@example.com'}):
            with self.subTest(config=config), override_settings(**config):
                with self.assertRaises(ProviderError):
                    Tranzila()
        for amount in ('10.00', Decimal('NaN'), Decimal('0'), Decimal('-1'),
                       Decimal('1.001'), Decimal('Infinity')):
            with self.subTest(amount=amount), self.assertRaises(ProviderError):
                Tranzila().handshake('id', amount, 'ILS')
        post.assert_not_called()

    @patch('billing.tranzila.requests.post')
    def test_network_errors_redacted_and_not_retried(self, post):
        post.side_effect = requests.Timeout('private-secret')
        with self.assertRaisesMessage(ProviderError, 'Tranzila request could not be confirmed.'):
            Tranzila().handshake('id', Decimal('10'), 'ILS')
        self.assertEqual(post.call_count, 1)

    @patch('billing.tranzila.requests.post')
    def test_rejects_redirect_oversized_and_bad_handshake(self, post):
        response = self.response({})
        response.iter_content.return_value = [b'x' * (Tranzila.MAX_RESPONSE_BYTES + 1)]
        for bad in (response, self.response({}, 302),
                    self.response({'error_code': False, 'thtk': 'token'}),
                    self.response({'error_code': 1, 'thtk': 'token'}),
                    self.response({'error_code': 0, 'thtk': '<script>'})):
            post.return_value = bad
            with self.assertRaises(ProviderError):
                Tranzila().handshake('id', Decimal('10'), 'ILS')

    def record(self, **updates):
        return {'index': 123, 'amount': '10.00', 'currency': '1',
                'child_terminal': 'testterminal', 'processor_response_code': '000',
                'tranmode': 'A', 'txn_type': 'DEBIT', 'user_defined_1': 'checkout-123',
                'transtatus': 1,
                'user_defined_20': 'checkout-123', 'credit_card_token': 'SENSITIVE', **updates}

    @patch('billing.tranzila.requests.post')
    def test_lookup_sanitizes_and_validates_server_record(self, post):
        post.return_value = self.response({'transactions': [self.record()]})
        result = Tranzila().lookup(123)
        self.assertEqual(post.call_args.args[0], Tranzila.REPORT_URL)
        self.assertEqual(json.loads(post.call_args.kwargs['data'])['transaction_index'], 123)
        self.assertEqual(result['checkout_id'], 'checkout-123')
        self.assertEqual(result['currency'], 'ILS')
        self.assertEqual(result['amount'], '10.00')
        self.assertEqual(result['transtatus'], '1')
        self.assertNotIn('SENSITIVE', json.dumps(result))
        for records in ([], [self.record(), self.record()], [self.record(index=124)],
                        [self.record(child_terminal='other')], [self.record(currency='garbage')],
                        [self.record(amount='NaN')], [self.record(user_defined_1=None)]):
            post.return_value = self.response({'transactions': records})
            with self.assertRaises(ProviderError):
                Tranzila().lookup(123)

    @patch('billing.tranzila.requests.post')
    def test_lookup_status_is_a_required_sanitized_scalar(self, post):
        for status in (1, '1', 'APPROVED'):
            post.return_value = self.response({'transactions': [self.record(transtatus=status)]})
            self.assertEqual(Tranzila().lookup(123)['transtatus'], str(status))
        missing = self.record()
        del missing['transtatus']
        for record in (missing, *(self.record(transtatus=value) for value in
                      (None, True, False, 1.0, {}, [], '', ' ', '<script>', 'x' * 33))):
            post.return_value = self.response({'transactions': [record]})
            with self.assertRaises(ProviderError):
                Tranzila().lookup(123)
