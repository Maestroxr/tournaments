"""Server-only DirectNG adapter; terminal test/live mode is configured by Tranzila.

Sources: docs.tranzila.com/docs/payments-and-billing/{authentication,
handshake-v2/createhandshakev2,iframe-integration-directng} and
docs.tranzila.com/docs/reports/tranzila-transaction-reports-api/gettransactions.
Never regard a browser redirect/Notify payload as proof of payment.
"""
import hashlib
import hmac
import json
import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import requests
from django.conf import settings


class ProviderError(Exception):
    pass


def _https_url(value):
    try:
        url = urlsplit(value)
        valid = (url.scheme == 'https' and url.hostname and not url.username
                 and not url.password and not url.fragment and url.port in (None, 443)
                 and not any(ord(char) < 33 for char in value))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ProviderError('Tranzila requires configured HTTPS callback URLs.')
    return value


class Tranzila:
    HANDSHAKE_URL = 'https://api.tranzila.com/v2/handshake/create'
    REPORT_URL = 'https://report.tranzila.com/v1/transaction'
    MAX_RESPONSE_BYTES = 1024 * 1024
    CURRENCIES = {'ILS': '1', 'USD': '2', 'EUR': '978', 'GBP': '826'}

    def __init__(self):
        self.terminal = getattr(settings, 'TRANZILA_TERMINAL', '')
        self.app_key = getattr(settings, 'TRANZILA_APP_KEY', '')
        self.app_secret = getattr(settings, 'TRANZILA_APP_SECRET', '')
        if (getattr(settings, 'TRANZILA_ENABLED', False) is not True
                or getattr(settings, 'TRANZILA_ENVIRONMENT', '') not in ('test', 'live')
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.terminal)
                or not self.app_key or not self.app_secret):
            raise ProviderError('Tranzila is not configured or enabled.')
        self.return_url = _https_url(getattr(settings, 'TRANZILA_RETURN_URL', ''))
        self.notify_url = _https_url(getattr(settings, 'TRANZILA_NOTIFY_URL', ''))

    def _send(self, url, body):
        if url not in (self.HANDSHAKE_URL, self.REPORT_URL):
            raise ProviderError('Unsupported Tranzila endpoint.')
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(40)
        token = hmac.new((self.app_secret + timestamp + nonce).encode(),
                         self.app_key.encode(), hashlib.sha256).hexdigest()
        headers = {'Content-Type': 'application/json',
                   'X-tranzila-api-app-key': self.app_key,
                   'X-tranzila-api-request-time': timestamp,
                   'X-tranzila-api-nonce': nonce,
                   'X-tranzila-api-access-token': token}
        try:
            # No automatic retries or redirects; do not forward credentials elsewhere.
            with requests.post(url, data=body.encode(), headers=headers, timeout=(5, 20),
                               verify=True, allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise ValueError('Unexpected status')
                chunks, length = [], 0
                for chunk in response.iter_content(chunk_size=8192):
                    length += len(chunk)
                    if length > self.MAX_RESPONSE_BYTES:
                        raise ValueError('Oversized response')
                    chunks.append(chunk)
                result = json.loads(b''.join(chunks), parse_float=Decimal)
                if not isinstance(result, dict):
                    raise ValueError('Unexpected response')
                return result
        except (requests.RequestException, ValueError, OSError):
            # Neither raw request nor response nor credential-bearing exception escapes.
            raise ProviderError('Tranzila request could not be confirmed.') from None

    def handshake(self, checkout_id: str, amount: Decimal, currency: str) -> dict:
        if not isinstance(checkout_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', checkout_id):
            raise ProviderError('Invalid checkout identifier.')
        if (not isinstance(amount, Decimal) or not amount.is_finite()
                or amount <= 0 or amount > Decimal('99999999.99')
                or amount != amount.quantize(Decimal('.01')) or currency not in self.CURRENCIES):
            raise ProviderError('Invalid checkout amount or currency.')
        # JSON number, without an intermediate binary float or rounding.
        formatted = format(amount, '.2f')
        body = ('{"terminal_name":' + json.dumps(self.terminal) + ',"sum":' + formatted
                + ',"request_params":' + json.dumps({'checkout_id': checkout_id}) + '}')
        result = self._send(self.HANDSHAKE_URL, body)
        token = result.get('thtk')
        if (type(result.get('error_code')) is not int or result['error_code'] != 0
                or not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,512}', token)):
            raise ProviderError('Tranzila did not confirm the handshake.')
        return {'thtk': token, 'method': 'POST',
                'action': f'https://directng.tranzila.com/{self.terminal}/iframenew.php',
                'fields': {'sum': formatted, 'currency': self.CURRENCIES[currency],
                           'tranmode': 'A', 'cred_type': '1', 'thtk': token,
                           'checkout_id': checkout_id, 'DCdisable': checkout_id,
                           'success_url_address': self.return_url,
                           'fail_url_address': self.return_url,
                           'notify_url_address': self.notify_url}}

    def lookup(self, transaction_index: int) -> dict:
        """Return a minimal server-fetched record, not a payment approval decision.

        Terminal slot 1 must be named checkout_id; slot 20 must be DCdisable.
        The caller must match reference, amount, currency, terminal, successful
        debit mode and unique transaction before delivering any goods.
        """
        if type(transaction_index) is not int or transaction_index <= 0:
            raise ProviderError('Invalid transaction index.')
        result = self._send(self.REPORT_URL, json.dumps({
            'terminal_name': self.terminal, 'transaction_index': transaction_index}))
        records = result.get('transactions')
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ProviderError('Tranzila transaction could not be verified.')
        record = records[0]
        try:
            amount = Decimal(str(record['amount']))
            currency = {value: key for key, value in self.CURRENCIES.items()}[str(record['currency'])]
            if (type(record['index']) is not int or record['index'] != transaction_index
                    or record['child_terminal'] != self.terminal or not amount.is_finite()
                    or amount <= 0 or amount > Decimal('99999999.99')
                    or amount != amount.quantize(Decimal('.01'))):
                raise ValueError()
            fields = ('processor_response_code', 'tranmode', 'txn_type', 'user_defined_1', 'user_defined_20')
            if any(not isinstance(record.get(field), str) or len(record[field]) > 254 for field in fields):
                raise ValueError()
            # The report documents this field, but not its enum semantics.
            # Preserve its scalar value for merchant-confirmed matching upstream.
            raw_status = record['transtatus']
            if type(raw_status) not in (int, str):
                raise ValueError()
            status = str(raw_status)
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', status):
                raise ValueError()
        except (ValueError, InvalidOperation, KeyError, TypeError):
            raise ProviderError('Tranzila transaction could not be verified.') from None
        return {'transaction_index': transaction_index, 'amount': format(amount, '.2f'),
                'currency': currency, 'terminal': record['child_terminal'],
                'processor_response_code': record['processor_response_code'],
                'transtatus': status,
                'tranmode': record['tranmode'], 'txn_type': record['txn_type'],
                'checkout_id': record['user_defined_1'], 'duplicate_key': record['user_defined_20']}

    def report_page(self, date_from, date_to, page=1, page_size=100, checkout_id=None):
        """Read one bounded page; callers must continue until total is covered."""
        if date_from > date_to or not 1 <= page <= 1000 or not 1 <= page_size <= 1000:
            raise ProviderError('Invalid report range.')
        body = {
            'terminal_name': self.terminal, 'transaction_start_date': date_from.isoformat(),
            'transaction_end_date': date_to.isoformat(), 'page': page,
            'page_results': page_size, 'order_direction': 'asc'}
        if checkout_id is not None:
            if not isinstance(checkout_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', checkout_id):
                raise ProviderError('Invalid checkout identifier.')
            body['ufields'] = [{'name': 'checkout_id', 'operator': 'equals', 'value': checkout_id}]
        result = self._send(self.REPORT_URL, json.dumps(body))
        records = result.get('transactions')
        total = str(result.get('total', ''))
        if (not isinstance(records, list) or len(records) > page_size
                or any(not isinstance(row, dict) for row in records)
                or not total.isascii() or not total.isdecimal() or len(total) > 9):
            raise ProviderError('Invalid report response.')
        if int(total) < len(records) or ('error_code' in result and
                (type(result['error_code']) is not int or result['error_code'] != 0)):
            raise ProviderError('Report request was not successful.')
        return records, int(total)
