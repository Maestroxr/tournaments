"""Connection-owned waiting presence; heartbeats touch Redis, never game rows."""
import hashlib
import logging
import uuid
from functools import lru_cache
from threading import RLock

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone
from redis import Redis

logger = logging.getLogger(__name__)
GRACE_SECONDS = 15
LEASE_SECONDS = 45
PREFIX = 'club:entry:'
_memory = {}
_memory_lock = RLock()


def _uses_memory():
    return settings.CHANNEL_LAYERS['default']['BACKEND'].endswith('InMemoryChannelLayer')


@lru_cache(maxsize=4)
def _client(url):
    return Redis.from_url(url, socket_timeout=10, socket_connect_timeout=5,
                          decode_responses=True)


def _keys(fixture_id, seat):
    key = f'{PREFIX}{_database_identity()}:{fixture_id}:{seat}'
    return key, key + ':owners'


def _database_identity():
    # Test databases can share a Redis server with the local application.
    name = str(settings.DATABASES['default']['NAME'])
    return hashlib.sha256(name.encode()).hexdigest()[:12]


def _due_key():
    return f'{PREFIX}{_database_identity()}:due'


def group_name(fixture_id):
    return f'club_entry_{_database_identity()}_{fixture_id}'


def change(fixture_id, seat, token, channel, action, now=None):
    """Fence old-socket cleanup so it cannot cancel a resumed attempt."""
    timestamp = (now or timezone.now()).timestamp()
    identity = (fixture_id, seat, token)
    if _uses_memory():
        with _memory_lock:
            previous = _memory.get(identity)
            if action == 'join':
                _memory[identity] = (channel, timestamp + LEASE_SECONDS)
                return True
            if previous is None or previous[0] != channel:
                return False
            if action == 'leave':
                del _memory[identity]
            elif action == 'disconnect':
                _memory[identity] = (channel, min(previous[1], timestamp + GRACE_SECONDS))
            elif previous[1] > timestamp:
                _memory[identity] = (channel, timestamp + LEASE_SECONDS)
            else:
                return False
            return True
    keys = _keys(fixture_id, seat)
    return bool(_client(settings.REDIS_URL).eval('''
        local token, owner, action = ARGV[1], ARGV[2], ARGV[3]
        local now, lease, grace = tonumber(ARGV[4]), tonumber(ARGV[5]), tonumber(ARGV[6])
        if action ~= 'join' and redis.call('HGET', KEYS[2], token) ~= owner then return 0 end
        local expiry = tonumber(redis.call('ZSCORE', KEYS[1], token))
        if action == 'leave' then
            redis.call('ZREM', KEYS[1], token)
            redis.call('HDEL', KEYS[2], token)
            redis.call('ZREM', KEYS[3], ARGV[7])
        else
            if action ~= 'join' and (not expiry or expiry <= now) then return 0 end
            local until_at = now + lease
            if action == 'disconnect' then until_at = math.min(expiry, now + grace) end
            redis.call('ZADD', KEYS[1], until_at, token)
            redis.call('HSET', KEYS[2], token, owner)
            redis.call('ZADD', KEYS[3], until_at, ARGV[7])
            redis.call('EXPIRE', KEYS[1], lease + grace + 10)
            redis.call('EXPIRE', KEYS[2], lease + grace + 10)
        end
        return 1
    ''', 3, *keys, _due_key(), token, channel, action, timestamp,
        LEASE_SECONDS, GRACE_SECONDS, f'{fixture_id}:{seat}:{token}'))


def seat_present(fixture_id, seat, now):
    timestamp = now.timestamp()
    if _uses_memory():
        with _memory_lock:
            return any(key[:2] == (fixture_id, seat) and value[1] > timestamp
                       for key, value in _memory.items())
    # Broker errors propagate: an outage must never manufacture a no-show winner.
    return bool(_client(settings.REDIS_URL).zcount(_keys(fixture_id, seat)[0],
                                                  f'({timestamp}', '+inf'))


def notify_fixture(fixture_id):
    try:
        async_to_sync(get_channel_layer().group_send)(group_name(fixture_id), {
            'type': 'club.entry_changed', 'fixture_id': fixture_id,
            'notification_id': uuid.uuid4().hex,
            'published_at': timezone.now().isoformat(),
        })
    except Exception:
        logger.exception('event=entry_state_delivery_failed fixture_id=%s', fixture_id)


def expire_presence(now=None):
    """The existing deadline worker also cleans leases after process failure."""
    timestamp = (now or timezone.now()).timestamp()
    fixtures = set()
    if _uses_memory():
        with _memory_lock:
            expired = [key for key, value in _memory.items() if value[1] <= timestamp][:100]
            for key in expired:
                del _memory[key]
                fixtures.add(key[0])
    else:
        client = _client(settings.REDIS_URL)
        for member in client.zrangebyscore(_due_key(), '-inf', timestamp, start=0, num=100):
            fixture, seat, token = member.split(':')
            removed = client.eval('''
                local due = tonumber(redis.call('ZSCORE', KEYS[3], ARGV[1]))
                if not due or due > tonumber(ARGV[3]) then return 0 end
                local expiry = tonumber(redis.call('ZSCORE', KEYS[1], ARGV[2]))
                if expiry and expiry > tonumber(ARGV[3]) then return 0 end
                redis.call('ZREM', KEYS[1], ARGV[2])
                redis.call('HDEL', KEYS[2], ARGV[2])
                redis.call('ZREM', KEYS[3], ARGV[1])
                return 1
            ''', 3, *_keys(fixture, seat), _due_key(), member, token, timestamp)
            if removed:
                fixtures.add(int(fixture))
    for fixture_id in fixtures:
        notify_fixture(fixture_id)
    return len(fixtures)
