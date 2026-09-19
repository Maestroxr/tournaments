# Direct game formats and financial contract

Reviewed against local code: 2026-09-19. Configuration comes from DirectPlaySettings.format_profiles. This document describes code, not active database values or a production rollout.

## Creation and access

New clients must send game_format=match|money. mode=match|friend determines public/private access. quick-match uses money; public tables, friend tables and match-search use match. quote() in tournaments/frontend/game_formats.py enforces this mapping, validates profile switches and allowed stakes/options, and chooses server-owned money-game defaults. Omitting game_format no longer creates a new legacy table. Existing legacy tables retain their compatibility paths.

Profiles control access, clocks, point targets, cube options and fees. New match contracts require Crawford; a one-point match cannot use the cube. Money games settle after one game. Rule snapshots travel to the game server in signed tickets.

## Dynamic exposure and reservation

calculate_dynamic_params(balance, stake, profile, mars_enabled, is_quick) calculates affordability, allowed_doubles, max_cube and max_exposure. In the quick/money branch it uses the balance, stake and a Mars factor of 2 when enabled (1 otherwise); it does not apply the old fixed loss-limit/profile cube cap. The non-quick branch keeps configured limits. If no balance is supplied, the legacy helper fallback still uses loss_limit_multiplier.

required_reserve(table) prioritizes dynamic_reserve_multiplier, then reserve_multiplier, then the legacy format fallback. Matching can reduce the contract to shared exposure and release excess held funds. Do not recalculate an existing game's contract using today's profile. Creation reserves funds; joining reserves the other player's liability. Waiting search cancellation releases the reservation.

## Settlement

For match, transfer is the agreed fixed stake. For money, transfer is min(required_reserve(table), stake × final cube × win multiplier). Win multipliers are single=1, gammon=2, backgammon=3; Jacoby reduces the multiplier to 1 when the cube is 1. The fee is calculated on the actual transfer and deducted from the winner's profit. The winner's own reserve and the loser's unused reserve are returned. Cancellation returns held reserves.

Only the authenticated game result can settle a linked table. The code validates room, status, winner, funding and financial result before writes. Duplicate delivery must not pay twice. Server adjudication determines forfeits/timeouts; client labels are not financial authority.

## Current contract gap

The quick calculation can return max_cube above 64 (its loop permits values up to 2^20), but settle() accepts only 1,2,4,8,16,32,64, even when dynamic_max_cube is larger. Align calculation, signed contract, game enforcement and settlement before treating every calculated double as supported. This is a static-code finding, not a newly executed financial test.

## Related code and checks

[Calculations and settlement](tournaments/frontend/game_formats.py), [API and serialization](tournaments/frontend/api.py), [models](tournaments/tournaments/models.py), [player flows](../GAME_MODES_AND_RULES.he.md), [rating](docs/RATING_POLICY.he.md).

Relevant existing suites include frontend.test_game_formats, frontend.test_head_to_head, tournaments.test_ratings, gamelink.test_ratings, game.tests.integration.test_formats and game.link.tests, plus HeadToHeadView and DirectPlayView frontend tests. Apply all pending migrations in both services for the version being deployed. Old statements about a specific migration already being applied are historical, not an inspection of the current database.
