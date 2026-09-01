export function tournamentStateLabel(state: string): string {
  if (state === 'draft') return 'Draft setup'
  if (state === 'open') return 'Open for registration'
  if (state === 'active') return 'In progress'
  if (state === 'finished') return 'Completed'
  return state
}

export function tournamentStateFilterLabel(state: string): string {
  if (state === 'current') return 'Current tournaments'
  if (state === 'all') return 'All tournament states'
  if (state === 'draft') return 'Draft setup'
  if (state === 'open') return 'Open for registration'
  if (state === 'active') return 'In progress'
  if (state === 'finished') return 'Completed / results'
  return state
}

export function timeControlLabel(value: string): string {
  if (value === 'none') return 'No clock'
  if (value === 'fast') return 'Fast clock'
  if (value === 'normal') return 'Standard clock'
  if (value === 'slow') return 'Slow clock'
  return value
}

export function transferKindLabel(kind: string): string {
  if (kind === 'deposit') return 'Admin deposit'
  if (kind === 'withdrawal') return 'Admin withdrawal'
  if (kind === 'tournament_entry') return 'Tournament entry fee'
  if (kind === 'tournament_refund') return 'Tournament refund'
  if (kind === 'tournament_prize') return 'Tournament prize'
  return kind.replaceAll('_', ' ')
}
