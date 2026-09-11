# Direct game formats

New clients send `game_format: "match" | "money"` separately from `mode: "match" | "friend"`; quick matchmaking has its own endpoint. Configuration lives in the admin Games → Formats and rules screen, or `DirectPlaySettings.format_profiles` in Django admin.

Each format controls stakes, access methods, clocks, cube availability and limit, fee percentage, and point targets (match only). Money games have Jacoby and a loss-limit multiplier; they always settle after one game. Crawford is mandatory for the new match format, including no cube in a one-point match.

The fee is a percentage of the actual amount transferred by the loser, deducted from the winner's profit. Match transfer is the fixed stake. Money transfer is `min(stake × cube × win multiplier, stake × loss-limit multiplier)`. Jacoby removes the gammon/backgammon multiplier before the first accepted double. A declined double uses the current, unaccepted cube value. For unilateral exits/timeouts, the game server derives the win multiplier from the current board (one if the loser has borne off, otherwise two or three for a checker on the bar/in the winner's home). This rule is displayed to players.

Creation reserves the host's maximum liability with a wallet debit; joining reserves the guest's liability. The winner receives their reservation back plus the transfer less the fee. The loser receives unused reservation back. Cancellation returns reservations. Quick search holds the largest selected liability until settlement/cancellation; matching selects the smallest shared stake and requires identical rule snapshots and format. Players can cancel waiting searches to release the hold.

Table snapshots are immutable and carried to the game engine by signed tickets. Results are server-derived and returned through the existing authenticated callback. Missing or invalid money results are rejected without releasing funds; duplicate callbacks do not pay twice. Disabling a profile/access blocks creation and joining, while already funded games retain their contract.

Older clients omitting `game_format` retain the existing fixed-stake/fee-only paths and are managed by the labelled Legacy settings. They cannot bypass the match format's enabled/access switches. Existing tables migrate to `legacy` and retain their settlement semantics.

## Local rollout

Migration `0023_game_formats` adds profiles and immutable table contracts and has been applied to the local database. Deploy the tournaments backend, player/admin frontends, and the separate game backend/frontend together; apply migrations before serving the new UI. No production deployment was performed.

Useful automated checks:

* Tournaments: `manage.py test frontend.test_game_formats frontend.test_head_to_head`.
* Engine: `manage.py test game.test_formats game.link.tests`; general engine suite also requires the Elixir dice service.
* Player: `vitest run src/views/__tests__/HeadToHeadView.test.ts --environment jsdom`.
* Admin: `vitest run src/pages/DirectPlayView.spec.ts src/components/AppTabs.spec.ts`.

Use test-only environment configuration for Django checks, never production signing secrets. Browser verification of the admin settings requires an authenticated staff session.
