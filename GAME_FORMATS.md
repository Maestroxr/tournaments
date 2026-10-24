# Direct game formats and financial contract

Reviewed against local code: 2026-10-24. Public Match and money configuration comes from DirectPlaySettings.format_profiles; Friend uses independent friend_rules and friend_game_fee. Money clocks use money_time_control. This document describes code, not active database values or a production rollout.

## Creation and access

New clients must send game_format=match|money. mode=match|friend determines public/private access. quick-match uses money; public tables, friend tables and match-search use match. quote() in tournaments/frontend/game_formats.py enforces this mapping, validates profile switches and allowed stakes/options, and chooses server-owned money-game defaults. Omitting game_format no longer creates a new legacy table. Existing legacy tables retain their compatibility paths.

Profiles control public Match and money access, point targets, cube options and fees. Friend availability, clocks, targets and cube limit are independent; its per-player fee is price per target point × target points. Money clocks are server-owned and fixed by money_time_control, with the original normal/first-option fallback for an uninitialized setting. Open Sage uses practice_rules for selectable targets and clocks. New match contracts require Crawford; a one-point match cannot use the cube. Money games settle after one game. Rule snapshots travel to the game server in signed tickets.

## Dynamic exposure and reservation

calculate_dynamic_params(balance, stake, profile, mars_enabled, is_quick) calculates affordability, allowed_doubles, max_cube and max_exposure. In the quick/money branch it uses the balance, stake and a Mars factor of 2 when enabled (1 otherwise); it does not apply the old fixed loss-limit/profile cube cap. The non-quick branch keeps configured limits. If no balance is supplied, the legacy helper fallback still uses loss_limit_multiplier.

required_reserve(table) prioritizes dynamic_reserve_multiplier, then reserve_multiplier, then the legacy format fallback. Matching can reduce the contract to shared exposure and release excess held funds. Do not recalculate an existing game's contract using today's profile. Creation reserves funds; joining reserves the other player's liability. Waiting search cancellation releases the reservation.

## Settlement

For match, transfer is the agreed fixed stake. For money, transfer is min(required_reserve(table), stake × final cube × win multiplier). Win multipliers are single=1, gammon=2, backgammon=3; Jacoby reduces the multiplier to 1 when the cube is 1. The fee is calculated on the actual transfer and deducted from the winner's profit. The winner's own reserve and the loser's unused reserve are returned. Cancellation returns held reserves.

Only the authenticated game result can settle a linked table. The code validates room, status, winner, funding and financial result before writes. Duplicate delivery must not pay twice. Server adjudication determines forfeits/timeouts; client labels are not financial authority.

## Cube contract compatibility

Quick calculation can return max_cube above 64, up to 2^20. Money-game ticket validation accepts positive powers of two within that existing range; match tickets retain their fixed cube choices up to 64. Settlement validates the final money cube against the table's frozen dynamic_max_cube (or its legacy snapshot fallback), rather than imposing another fixed 64 cap. Reservation, Jacoby, multiplier and transfer-cap behavior are unchanged. Deploy the corresponding game ticket verifier with the club settlement change. Local isolated checks are distinct from production validation.

## Related code and checks

[Calculations and settlement](tournaments/frontend/game_formats.py), [API and serialization](tournaments/frontend/api.py), [models](tournaments/tournaments/models.py), [player flows](../GAME_MODES_AND_RULES.he.md), [rating](docs/RATING_POLICY.he.md).

The settings/data migration and scoped-write contract are documented in [game admin settings](docs/GAME_ADMIN_SETTINGS.he.md). Migration tournaments.0035_game_mode_settings copies current Friend choices and cube limit and preserves the effective money clock; it has not been applied in this change.

Relevant suites include frontend.test_game_mode_settings, frontend.test_game_formats, frontend.test_head_to_head, tournaments.test_ratings, gamelink.test_ratings, game.tests.integration.test_formats and game.link.tests, plus HeadToHeadView and DirectPlayView frontend tests. Apply all pending migrations in both services for the version being deployed. Old statements about a specific migration already being applied are historical, not an inspection of the current database.
