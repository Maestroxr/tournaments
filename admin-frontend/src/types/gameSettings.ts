import type { DirectPlaySettings, FormatProfiles, GameModeRules } from './directPlay'

export type SettingsSection =
  'match' | 'friend' | 'money' | 'practice' | 'tournaments' | 'settings' | 'legacy'
export type GamesSection = SettingsSection | 'monitor'
export const settingsSections: SettingsSection[] = [
  'match',
  'friend',
  'money',
  'practice',
  'tournaments',
  'settings',
  'legacy',
]
export interface GameSettingsForm {
  format_profiles: FormatProfiles
  friend_rules: GameModeRules & { max_cube: number }
  practice_rules: { target_points: number[]; time_controls: string[] }
  money_time_control: string
  enabled: boolean
  friend_game_fee: number
  ai_game_fee: number
  tournament_fee_percent: number
  coin_grant_enabled: boolean
  coin_grant_amount: number
  coin_grant_interval_hours: number
  game_rules: DirectPlaySettings['game_rules']
  stake_amounts: number[]
  head_to_head_fee_percent: number
}
