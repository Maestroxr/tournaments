import type { TournamentFixture } from '@/types/tournamentProgress'

type LiveSnapshot = TournamentFixture['live']
type StatusSnapshot = NonNullable<LiveSnapshot> & { event_revision: number }

export function isStatusEvent(live: LiveSnapshot): live is StatusSnapshot {
  return typeof live?.event_revision === 'number' && live.event_revision > 0
}

function shouldApplySnapshot(incoming: LiveSnapshot, previous: LiveSnapshot): boolean {
  if (isStatusEvent(incoming)) {
    return incoming.event_revision > (previous?.event_revision ?? 0)
  }
  if (isStatusEvent(previous)) return false
  if (incoming?.sequence != null && previous?.sequence != null) {
    return incoming.sequence >= previous.sequence
  }
  return true
}

export function applyFixtureSnapshot(fixture: TournamentFixture, incoming: LiveSnapshot, receivedAt: Date): boolean {
  if (fixture.is_confirmed || fixture.admin_resolution || fixture.operational_status === 'completed') return false
  if (!shouldApplySnapshot(incoming, fixture.live)) return false
  fixture.live = incoming
  if (incoming?.status === 'playing') {
    fixture.stalled = incoming.state.presence?.needsAdminAdjudication === true
    if (fixture.score1 == null && fixture.score2 == null && fixture.confirmations === 0) {
      fixture.operational_status = fixture.stalled ? 'stalled' : 'playing'
    }
    fixture.last_status_at = receivedAt.toISOString()
    fixture.last_activity_at = isStatusEvent(incoming) ? null : receivedAt.toISOString()
    fixture.started_at = incoming.started_at || fixture.started_at || (
      isStatusEvent(incoming) ? null : receivedAt.toISOString()
    )
    if (fixture.started_at) {
      fixture.duration_seconds = Math.max(0, Math.floor((receivedAt.getTime() - Date.parse(fixture.started_at)) / 1000))
    }
  }
  return true
}
