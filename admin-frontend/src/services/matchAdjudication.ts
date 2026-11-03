import type { TournamentFixture } from '@/types/tournamentProgress'

export function isMatchSettled(fixture: TournamentFixture): boolean {
  return (
    fixture.is_confirmed || !!fixture.admin_resolution || fixture.operational_status === 'completed'
  )
}

export function needsMatchAdjudication(fixture: TournamentFixture): boolean {
  return !isMatchSettled(fixture) && fixture.live?.state.presence?.needsAdminAdjudication === true
}
