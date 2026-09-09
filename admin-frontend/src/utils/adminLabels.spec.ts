import { describe, expect, it } from 'vitest'
import { timeControlDetail, timeControlLabel } from './adminLabels'

const translate = (key: string, params: Record<string, string | number> = {}) => {
  const messages: Record<string, string> = {
    'tournaments.fast': 'Fast',
    'tournaments.normal': 'Normal',
    'tournaments.slow': 'Slow',
    'tournaments.noClock': 'No clock',
    'tournaments.clockMinute': '{count} min',
    'tournaments.clockMinutes': '{count} min',
    'tournaments.clockSecond': '{count} sec',
    'tournaments.clockSeconds': '{count} sec',
    'tournaments.timeControlDetail':
      '{bank} per player · {rate}/point · 10-second delay each turn',
    'tournaments.timeControlSummary': '{pace} · {detail}',
  }
  return Object.entries(params).reduce(
    (text, [name, value]) => text.replace(`{${name}}`, String(value)),
    messages[key] ?? key,
  )
}

describe('timeControlLabel', () => {
  it('recalculates each player bank from the target score', () => {
    expect(timeControlLabel('fast', 5, translate)).toContain('2 min 30 sec per player')
    expect(timeControlLabel('fast', 7, translate)).toContain('3 min 30 sec per player')
    expect(timeControlDetail('normal', 5, translate)).toBe(
      '5 min per player · 1 min/point · 10-second delay each turn',
    )
    expect(timeControlLabel('slow', 5, translate)).toContain('10 min per player')
  })

  it('keeps no-clock matches unlimited regardless of the target score', () => {
    expect(timeControlLabel('none', 3, translate)).toBe('No clock')
    expect(timeControlLabel('none', 9, translate)).toBe('No clock')
  })
})
