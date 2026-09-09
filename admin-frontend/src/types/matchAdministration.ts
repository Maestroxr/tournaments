export type MatchAdminAction = 'score' | 'finish' | 'advance' | 'disqualify' | 'refund'
export type MatchPanelSection = 'live' | 'score' | 'players' | 'times' | 'note' | 'history'
export interface MatchAdminPlayer {
  id: number
  name: string
  disqualified: boolean
  refundable: string
}
export interface MatchAuditSnapshot {
  score?: Array<number | null>
  winner_id?: number | null
  participant_id?: number
  note?: string
  refund?: { participant_id: number; amount: string; transaction_id: number }
}
export interface MatchAuditEvent {
  id: number
  action: string
  actor: string | null
  at: string
  reason: string
  before: MatchAuditSnapshot
  after: MatchAuditSnapshot
}
export interface MatchAdministration {
  fixture_id: number
  version: string
  note: string
  can_rule: boolean
  result: {
    score: Array<number | null>
    winner_id: number | null
    resolution: string
    confirmed: boolean
  }
  players: MatchAdminPlayer[]
  target_points: number
  needs_admin_adjudication: boolean
  absent_since: Partial<Record<'white' | 'black', number>>
  times: {
    connection_created_at: string | null
    live_started_at: string | null
    ended_at: string | null
  }
  history: MatchAuditEvent[]
}
