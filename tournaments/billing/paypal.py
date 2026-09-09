"""PayPal sandbox REST adapter. No browser-supplied prices, IDs or callback URLs."""
import base64
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings


class ProviderError(Exception):
    pass


def provider_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', value):
        raise ValueError('Invalid provider identifier.')
    return value


class PayPal:
    base = 'https://api-m.sandbox.paypal.com'

    def __init__(self):
        if (not settings.BILLING_ENABLED or settings.PAYPAL_ENVIRONMENT != 'sandbox'
                or not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET):
            raise ProviderError('Sandbox billing is not configured.')
        self.token = None

    def _send(self, path, method, data, headers):
        request = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read(1024 * 1024)
                return json.loads(raw) if raw else {}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            # Never expose OAuth credentials or raw payer data in errors/logs.
            raise ProviderError('PayPal is unavailable; retry the same operation.') from error

    def request(self, method, path, body=None, request_id=None):
        if not self.token:
            auth = base64.b64encode(
                f'{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}'.encode()
            ).decode()
            result = self._send('/v1/oauth2/token', 'POST', b'grant_type=client_credentials', {
                'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded',
            })
            self.token = result.get('access_token')
            if not self.token:
                raise ProviderError('PayPal authentication failed.')
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        if request_id:
            headers['PayPal-Request-Id'] = str(request_id)
        return self._send(path, method, json.dumps(body).encode() if body is not None else None, headers)

    def verify(self, headers, event):
        fields = {
            'auth_algo': 'PAYPAL-AUTH-ALGO', 'cert_url': 'PAYPAL-CERT-URL',
            'transmission_id': 'PAYPAL-TRANSMISSION-ID',
            'transmission_sig': 'PAYPAL-TRANSMISSION-SIG',
            'transmission_time': 'PAYPAL-TRANSMISSION-TIME',
        }
        if not settings.PAYPAL_WEBHOOK_ID or any(not headers.get(h) for h in fields.values()):
            return False
        body = {key: headers[header] for key, header in fields.items()}
        body.update(webhook_id=settings.PAYPAL_WEBHOOK_ID, webhook_event=event)
        return self.request('POST', '/v1/notifications/verify-webhook-signature', body).get('verification_status') == 'SUCCESS'

    def plan(self, identifier):
        return self.request('GET', f'/v1/billing/plans/{provider_id(identifier)}')

    def create(self, subscription):
        result = self.request('POST', '/v1/billing/subscriptions', {
            'plan_id': subscription.plan_id, 'custom_id': str(subscription.pk),
            'application_context': {
                'shipping_preference': 'NO_SHIPPING', 'user_action': 'SUBSCRIBE_NOW',
                'return_url': settings.BILLING_RETURN_URL + '?checkout=returned',
                'cancel_url': settings.BILLING_RETURN_URL + '?checkout=cancelled',
            },
        }, subscription.pk)
        approval = next((link['href'] for link in result.get('links', []) if link.get('rel') == 'approve'), '')
        parsed = urlsplit(approval)
        if (parsed.scheme != 'https' or parsed.hostname != 'www.sandbox.paypal.com'
                or parsed.username or parsed.port not in (None, 443)):
            raise ProviderError('PayPal did not return a valid sandbox approval URL.')
        return provider_id(result['id']), approval

    def subscription(self, identifier):
        return self.request('GET', f'/v1/billing/subscriptions/{provider_id(identifier)}')

    def cancel(self, subscription):
        self.request('POST', f'/v1/billing/subscriptions/{provider_id(subscription.provider_id)}/cancel',
                     {'reason': 'Customer requested cancellation.'}, f'cancel-{subscription.pk}')

    def refund(self, payment):
        # Subscriptions emit SALE IDs; these are not v2 capture IDs.
        return self.request('POST', f'/v1/payments/sale/{provider_id(payment.provider_id)}/refund',
                            {}, f'refund-{payment.pk}')
