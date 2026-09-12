<div align="center">
  <h1><a href="https://github.com/kostrykin/tournaments">tournaments</a><br>
  <a href="https://github.com/kostrykin/tournaments/actions/workflows/testsuite.yml"><img src="https://github.com/kostrykin/tournaments/actions/workflows/testsuite.yml/badge.svg"></a>
  <a href="https://github.com/kostrykin/tournaments/actions/workflows/testsuite.yml"><img src="https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/kostrykin/bb85310a74d6b05330d230443007b878/raw/tournaments.json" /></a>
  </h1>
</div>

## Business model and legal review

The proposed subscription, tournament, prize, Coins, and existing-wallet transition rules are documented in [the Hebrew business and legal rules draft](BUSINESS_AND_LEGAL_RULES.he.md). Company-funded prizes and free entry do not by themselves establish legality. The new model must not launch payments or prizes before the required Israeli legal and accounting reviews and implementation checks are completed. The draft is not a professional approval or an implemented runtime restriction.

## Beta budget and launch plan

The [Hebrew beta launch plan](BETA_LAUNCH_PLAN.he.md) defines a proposed two-month budget, 5% and 10% paid-conversion scenarios, the corrected ILS 152,000 annual prize total, recruitment cohorts, measurement definitions, support operations, and expansion criteria. A separate [sponsor proposal draft](BETA_SPONSOR_PROPOSAL.he.md) specifies deliverables and funding conditions. These are planning documents; funding, recruitment, analytics implementation, and a full month of observed cohort data remain outstanding.

## Screenshots

<div align="center">
<p><kbd><img width="1128" src="https://github.com/kostrykin/tournaments/assets/6557139/44c98a04-8613-447a-82fa-30abede06ea3"></kbd></p>
<p><kbd><img width="1128" src="https://github.com/kostrykin/tournaments/assets/6557139/4fefa3b0-8b98-47bf-9a7e-8812d8f3064a"></kbd></p>
</div>

## Installation

### Initial setup

Create virtual environment:
```bash
python -m venv venv
```
Activate virtual environment:
```bash
source venv/bin/activate
```

Install dependencies into virtual environment:
```bash
pip install -r requirements.txt
```

#### Prerequisites after initial setup

Activate virtual environment: (if not done yet)
```bash
source venv/bin/activate
```

Change into the `tournaments` directory:
```
cd tournaments
```

#### Initialize/update the database

This is only required after the initial setup, or when updating to new versions:

1. Create/update the database:
    ```bash
    python manage.py migrate
    ```

2. Create a superuser: (only after the initial setup)
    ```bash
    python manage.py createsuperuser
    ```

#### Day-to-day use

Run tests:
```bash
python manage.py test
```

Compute test coverage:
```bash
coverage run --source='.' manage.py test
coverage html
```
This assumes that *coverage.py* was installed (e.g., `pip install coverage`).

Run the local server:
```bash
python manage.py runserver
```

## Game link (playing fixtures on an external game server)

A fixture can be played on a linked game server instead of being scored by hand. A player presses
**Go to game** on the tournament progress page, is handed a single-use ticket, plays, and the game
server reports the result back — which confirms the fixture without any human votes and advances
the tournament. The manual scoring path is untouched and stays available for every fixture that was
not reported this way.

**The feature ships disabled.** With `GAMELINK_ENABLED` off, the button never renders, the
predicate behind it refuses before it touches the database, and the callback endpoint returns 404.
Turning it off again is a complete rollback.

### Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `GAMELINK_ENABLED` | — | `1` to turn the feature on. Anything else is off, which is the default. |
| `GAMELINK_BACKGAMMON_URL` | when enabled | Base URL of the game server, `https://…`, no path. |
| `GAMELINK_TICKET_SECRET` | when enabled | Signs the tickets this server issues. |
| `GAMELINK_RESULT_SECRETS` | when enabled | Comma-separated list. Verifies results the game server posts back; **every** entry is tried. |
| `REDIS_URL` | production live admin | Redis connection URL for tournament progress WebSockets. |
| `CHANNEL_LAYER_BACKEND` | — | `redis` in production, `memory` for local development. Defaults are chosen from the Django settings module. |

Never commit any of these. Generate each one separately, per environment:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

A boot-time system check refuses to start the server when the feature is on outside `DEBUG` and the
configuration is weak — a missing or short secret, the same secret used for both channels, the
ticket secret reused as `SECRET_KEY`, or a base URL that is not `https://`. Run it with
`python manage.py check`; it fails loudly rather than degrading silently.

### Live admin progress

The tournament progress screen uses WebSockets for live game snapshots. Run the tournament server
with ASGI/Daphne, not a WSGI-only server, and make sure your reverse proxy forwards `/ws/` with
the WebSocket upgrade headers. Local development uses the in-memory channel layer automatically.
Production defaults to Redis; set `REDIS_URL` to the Redis instance shared by the tournament app
workers.

### Scheduled jobs

One cron entry, at whatever interval suits you — hourly is plenty:

```cron
0 * * * * cd /srv/tournaments/tournaments && ../venv/bin/python manage.py purge_expired
```

It forgets seen nonces older than an hour, deletes issued-ticket audit rows past their expiry, and
closes any game link still `pending` past its own expiry so the fixture goes back to being
manually scorable. It refuses to run — non-zero, no traceback — if `--nonce-hours` is set low
enough to weaken replay protection, because a nonce forgotten while its message is still inside the
timestamp window can be replayed.

> **The game server has a cron requirement of its own, and it is not optional.** Its `run_tasks` is
> the only retry path for a result this server refuses or fails to answer. Without it, one blip
> here loses a match result permanently and silently. See the backend README on that side.

### Recovering split one-player rooms

If an older client sent opponents into different fixtures, first cancel and detach the one-seat
rooms on the game server, then release their non-completed GameLink rows here. Both commands are a
dry run unless `--execute` is supplied, and both accept repeatable `--fixture-id` filters:

```bash
# game server
python manage.py cancel_linked_rooms --tournament-id 14
python manage.py cancel_linked_rooms --tournament-id 14 --execute

# tournaments server
python manage.py reset_active_game_links --tournament-id 14
python manage.py reset_active_game_links --tournament-id 14 --execute
```

The game-server command refuses to touch a room with two occupied seats. Completed links are also
never reset. After both commands, the players can use the corrected tournament-specific entry
button to provision one fresh room.

### Rotating a secret

Each verifier takes a **list** and each signer uses the **first** entry, which is what makes a
rotation possible with no window where valid messages bounce. For `GAMELINK_RESULT_SECRETS`, whose
signer is the game server:

1. Append the new secret to `GAMELINK_RESULT_SECRETS` here and deploy. Both old and new now verify.
2. Move the new secret to the front of the game server's `GAMELINK_RESULT_SECRET` and deploy there.
3. Remove the old secret from the list here and deploy.

`GAMELINK_TICKET_SECRET` rotates the same way in the other direction: add the new secret to the
game server's `GAMELINK_TICKET_SECRETS` list first, then switch this server's signer, then drop the
old one from the list.

Never do steps 1 and 2 in the other order, and never skip step 1 — that is precisely the window in
which valid messages are rejected.

### Enabling it

Enable the **game server first**. It can only accept tickets that nobody is yet able to mint, so
that half is inert on its own. Then enable this side. Rolling back is `GAMELINK_ENABLED=0` here:
the button disappears and manual scoring carries on untouched.

### Payments and membership

New purchases use Tranzila hosted checkout for coin packages and fixed-duration
memberships. Memberships are paid once and do not renew automatically. Prices,
currencies, quantities, and durations come from the admin catalog.

The retired PayPal plan, checkout, cancellation, refund, and webhook routes
return HTTP 410 without contacting a provider or changing records. Old PayPal
configuration is no longer used. Historical database records are preserved;
authenticated owners can still read membership status and download their private
payment records through `/api/billing/status` and `/api/billing/receipts/{uuid}`.
Existing paid access retains its original expiry and refund/reversal rules.

Keep `TRANZILA_ENABLED=0` until terminal acceptance tests pass. See
[Tranzila preparation](docs/TRANZILA_PREPARATION.he.md) for server configuration.
Payment tests simulate provider responses; they do not establish terminal readiness.

`TRANZILA_PURCHASES_ENABLED=0` keeps player purchases closed independently of
the provider connection. Use this switch to pause purchases while allowing
in-flight payments to verify. See [operations and acceptance](docs/TRANZILA_OPERATIONS.he.md)
for the player API, callback routes, reconciliation and manual refund procedures.

### Phone notification monitoring

The admin shell polls the staff-only `GET /api/admin/push-health` endpoint every
30 seconds while visible. A warning appears for missing push settings or the
`pywebpush` library, a missing/stale worker heartbeat, overdue delivery attempts,
and exhausted deliveries in either the tournament or direct-play queue. Failed
status requests show a monitoring warning instead of implying successful delivery.
Only counts, setting names and timestamps are returned; no signing keys or device
endpoints are exposed. These diagnostics do not confirm receipt on a phone.

Deploy the backend and admin frontend, run `python manage.py migrate`, and restart
the API and supervised `python manage.py run_push_notifications` worker. Migration
`frontend.0005_push_worker_status` stores a shared database heartbeat, which works
across API and worker processes. The worker is considered stale after the larger
of 120 seconds or three configured polling intervals. A worker running older code
does not report a heartbeat and will trigger a warning until restarted with this code.
The `--once` command records only a single run and does not replace a supervised worker.

For missing configuration, set `WEB_PUSH_PUBLIC_KEY`, `WEB_PUSH_PRIVATE_KEY` and
`WEB_PUSH_SUBJECT` in the API and worker environments. For stalled or failed
deliveries, inspect the worker process and provider connectivity. Exhausted
deliveries remain reported while their records are unresolved; viewing the warning
does not retry, remove, or mark deliveries successful.
