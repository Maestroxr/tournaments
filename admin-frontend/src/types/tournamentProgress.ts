export interface TournamentProgressPlayer {
  id: number | null
  user_id: number | null
  name: string | null
  username: string | null
}

export interface TournamentFixture {
  id: number
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
  levels: TournamentProgressLevel[]
}

export interface TournamentProgressData {
  tournament: {
    id: number
    name: string
    state: string
    participant_count: number
  }
  stages: Record<string, TournamentProgressStage>
  is_finished: boolean
  podium: Array<{
    id: number
    name: string
  }>
}
