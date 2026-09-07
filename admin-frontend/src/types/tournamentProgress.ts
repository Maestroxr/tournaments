export interface TournamentProgressPlayer {
  id: number | null
  user_id: number | null
  name: string | null
  username: string | null
}

export interface TournamentFixture {
  id: number
  stage_id?: string
  stage_name?: string
  round_name?: string
  round_index?: number
  is_current_round?: boolean
  operational_status?: 'playing' | 'waiting' | 'waiting_opponent' | 'review' | 'stalled' | 'completed' | 'upcoming'
  ready_at?: string | null
  started_at?: string | null
  last_activity_at?: string | null
  ended_at?: string | null
  duration_seconds?: number | null
  stalled?: boolean
  admin_resolution?: string
  winner_id?: number | null
  can_play?: boolean
  playability?: { can_play: boolean; reason: string; message?: string }
  bracket?: { position: number; winner_to: { fixture_id: number; player_slot: number } | null } | null
  player1: TournamentProgressPlayer | null
  player2: TournamentProgressPlayer | null
  score1: number | null
  score2: number | null
  confirmations: number
  is_confirmed: boolean
  required_confirmations: number
  editable: boolean
  has_confirmed: boolean
  live: {
    status: string
    state: {
      phase: string | null
      turn: string | null
      dice: number[] | null
      cube: number | null
    }
    match_score: { white: number; black: number }
  } | null
}

export interface TournamentProgressLevel {
  name?: string
  fixtures: TournamentFixture[]
}

export interface TournamentProgressStage {
  bracket_kind?: 'single_elimination' | null
  levels: TournamentProgressLevel[]
}

export interface TournamentProgressData {
  tournament: {
    id: number
    name: string
    state: string
    lifecycle_state?: string
    participant_count: number
    min_players?: number
  }
  stages: Record<string, TournamentProgressStage>
  is_finished: boolean
  podium: Array<{
    id: number
    name: string
  }>
  control_room?: {
    current_stage: string | null
    current_round: string | null
    counts: Record<'playing' | 'waiting' | 'waiting_opponent' | 'review' | 'stalled' | 'completed' | 'upcoming', number>
    waiting_players: Array<{
      id: number
      name: string
      user_id: number | null
      fixture_id: number
      round_name: string
    }>
    round_total: number
    round_completed: number
    stale_after_seconds: number
    generated_at: string
  }
}
