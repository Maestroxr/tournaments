export interface GameModeRules {
  enabled: boolean
  target_points: number[]
  time_controls: string[]
  doubling_options: boolean[]
}

export type GameRules = Record<'match' | 'friend' | 'quick', GameModeRules>

export interface FormatProfile extends GameModeRules {
  public: boolean
  private: boolean
  quick: boolean
  stake_amounts: number[]
  fee_percent: number
  max_cube: number
  loss_limit_multiplier: number
  jacoby: boolean
}
export type FormatProfiles = Record<'match' | 'money', FormatProfile>

export interface DirectPlaySettings {
  format_profiles?: FormatProfiles
  game_rules: GameRules
  stake_amounts?: number[]
  enabled: boolean
  friend_game_fee: string
  head_to_head_fee_percent: string
  tournament_fee_percent: string
  coin_grant_enabled: boolean
  coin_grant_amount: string
  coin_grant_interval_hours: number
  updated_at?: string
}

export interface DirectPlayTable {
  game_format?: 'legacy' | 'match' | 'money'
  rules_snapshot?: FormatProfile
  required_reserve?: string
  settlement?: { transfer?: string; fee?: string }
  id: number
  code: string
  mode: string
  host: string | null
  guest: string | null
  winner: string | null
  amount: string
  fee_percent: string
  fee_per_player: string
  target_points: number
  doubling_enabled: boolean
  status: string
  external_room_id: string | null
  created_at: string
  is_quick_match?: boolean
  host_id?: number
  guest_id?: number | null
  winner_id?: number | null
  time_control?: string
  updated_at?: string
  completed_at?: string | null
}

export interface DirectPlayTablesResponse {
  tables: DirectPlayTable[]
  history_total?: number
  history_limit?: number
}
