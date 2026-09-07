import type { Ref } from 'vue'
import { inject, type InjectionKey } from 'vue'

export interface TournamentWorkspaceSummary {
  id: number
  name: string
  state: string
  lifecycle_state?: string
  participant_count: number
  min_players?: number
  max_players?: number | null
  registration_summary?: {
    registered: number
    unpaid: number
    waitlisted: number
    attention: number
    ready: number
  }
}

export interface TournamentWorkspaceContext {
  tournament: Ref<TournamentWorkspaceSummary | null>
  refresh: () => Promise<void>
}

export const tournamentWorkspaceKey: InjectionKey<TournamentWorkspaceContext> =
  Symbol('tournament-workspace')

export function useTournamentWorkspace() {
  return inject(tournamentWorkspaceKey, null)
}
