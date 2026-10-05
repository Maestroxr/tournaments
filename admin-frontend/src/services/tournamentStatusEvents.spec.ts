import { describe, expect, it } from 'vitest'
import type { TournamentFixture } from '@/types/tournamentProgress'
import { applyFixtureSnapshot } from './tournamentStatusEvents'

const receivedAt = new Date('2026-10-05T10:05:00Z')
function fixture(extra: Partial<TournamentFixture> = {}): TournamentFixture {
  return {
    id: 1, player1: null, player2: null, score1: null, score2: null,
    confirmations: 0, is_confirmed: false, required_confirmations: 2,
    editable: false, has_confirmed: false, live: null, ...extra,
  }
}
function event(revision: number, needsAdmin = false): NonNullable<TournamentFixture['live']> {
  return {
    status: 'playing', sequence: 5, event_revision: revision,
    event_type: needsAdmin ? 'admin_required' : 'admin_cleared',
    started_at: '2026-10-05T10:00:00Z',
    state: { phase: 'moving', turn: 'white', dice: null, cube: 1,
      presence: { needsAdminAdjudication: needsAdmin } },
    match_score: { white: 0, black: 0 },
  }
}

describe('tournament status events', () => {
  it('orders admin transitions independently of game-action sequence', () => {
    const current = fixture()
    expect(applyFixtureSnapshot(current, event(2, true), receivedAt)).toBe(true)
    expect(current.operational_status).toBe('stalled')
    expect(applyFixtureSnapshot(current, event(3), receivedAt)).toBe(true)
    expect(current.operational_status).toBe('playing')
    expect(current.stalled).toBe(false)
    expect(applyFixtureSnapshot(current, event(2, true), receivedAt)).toBe(false)
    expect(current.live?.event_revision).toBe(3)
  })

  it('ignores duplicates without changing the last sync time', () => {
    const current = fixture()
    const live = event(1)
    applyFixtureSnapshot(current, live, receivedAt)
    expect(applyFixtureSnapshot(current, live, new Date('2026-10-05T10:06:00Z'))).toBe(false)
    expect(current.last_status_at).toBe(receivedAt.toISOString())
  })

  it('does not present the status delivery as game activity or a new start', () => {
    const current = fixture()
    applyFixtureSnapshot(current, event(2, true), receivedAt)
    expect(current.last_activity_at).toBeNull()
    expect(current.started_at).toBe('2026-10-05T10:00:00Z')
    expect(current.duration_seconds).toBe(300)
  })

  it('ignores a delayed legacy snapshot after a status event', () => {
    const current = fixture()
    applyFixtureSnapshot(current, event(2, true), receivedAt)
    const legacy = { status: 'playing', sequence: 100, state: event(1).state, match_score: event(1).match_score }
    expect(applyFixtureSnapshot(current, legacy, receivedAt)).toBe(false)
    expect(current.stalled).toBe(true)
  })

  it('preserves a submitted result and a completed fixture', () => {
    const review = fixture({ score1: 5, score2: 2, operational_status: 'review' })
    applyFixtureSnapshot(review, event(2, true), receivedAt)
    expect(review.operational_status).toBe('review')
    const completed = fixture({ is_confirmed: true, operational_status: 'completed' })
    expect(applyFixtureSnapshot(completed, event(2, true), receivedAt)).toBe(false)
    expect(completed.live).toBeNull()
  })
})
