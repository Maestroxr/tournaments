export type AdminNotificationSeverity = 'critical' | 'warning' | 'info'

export type AdminNotificationKind =
  | 'overdue'
  | 'waiting_players'
  | 'ready_to_start'
  | 'pending_matches'
  | 'draft'

export interface AdminNotification {
  notification_id: string
  id: number
  name: string
  state: string
  starts_at: string | null
  participant_count: number
  min_players: number
  max_players: number | null
  kind: AdminNotificationKind
  severity: AdminNotificationSeverity
  pending_matches?: number
  message: string
  action_label: string
  action_to: string
}

export interface AdminNotificationsPayload {
  updated_at: string
  total: number
  counts: Record<AdminNotificationSeverity, number>
  notifications: AdminNotification[]
}
