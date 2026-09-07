import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { buildBracket, BRACKET_CARD_HEIGHT } from './tournamentBracket'
import TournamentMatchesPanel from '@/components/tournament/TournamentMatchesPanel.vue'
import TournamentBracketMatch from '@/components/tournament/TournamentBracketMatch.vue'
import { useI18n } from '@/i18n'
import type { TournamentFixture, TournamentProgressStage } from '@/types/tournamentProgress'

function stage(players: number): TournamentProgressStage {
  const depth = Math.floor(Math.log2(players - 1))
  const levels = Array.from({ length: depth + 1 }, () => ({ fixtures: [] as TournamentFixture[] }))
  for (let p = 1; p < players; p++) {
    levels[depth - Math.floor(Math.log2(p))]!.fixtures.push({
      id: 100 + p, player1: null, player2: null, score1: null, score2: null,
      is_confirmed: false, confirmations: 0, required_confirmations: 2, has_confirmed: false, editable: false, live: null,
      bracket: { position: p, winner_to: p > 1 ? { fixture_id: 100 + Math.floor(p / 2), player_slot: 1 + p % 2 } : null },
    })
  }
  return { bracket_kind: 'single_elimination', levels }
}

describe('Tournament bracket', () => {
  it.each([2, 6, 8, 16, 32])('lays out %i players without card overlaps and with correct winner connections', players => {
    const layout = buildBracket(stage(players))!
    expect(layout.nodes).toHaveLength(players - 1)
    expect(layout.edges).toHaveLength(players - 2)
    for (const edge of layout.edges) expect(edge.to).toBe(100 + Math.floor((edge.from - 100) / 2))
    for (let c = 0; c < layout.columns.length; c++) {
      const column = layout.nodes.filter(n => n.column === c).sort((a, b) => a.y - b.y)
      column.slice(1).forEach((node, i) => expect(node.y - column[i]!.y).toBeGreaterThan(BRACKET_CARD_HEIGHT))
    }
    expect(layout.nodes.find(n => n.fixture.id === 101)!.center).toBe((layout.height + 44) / 2)
  })

  it('handles six-player byes without inventing extra matches or linking to the wrong semifinal', () => {
    const layout = buildBracket(stage(6))!
    expect(layout.edges.filter(edge => edge.from >= 104).map(edge => edge.to)).toEqual([102, 102])
    expect(layout.sources.has(103)).toBe(false)
    expect(layout.sources.get(101)?.[2]?.id).toBe(103)
  })

  it('does not depend on API fixture ordering', () => {
    const value = stage(8)
    value.levels.forEach(level => level.fixtures.reverse())
    const layout = buildBracket(value)!
    expect(layout.nodes.find(n => n.fixture.id === 104)!.y).toBeLessThan(layout.nodes.find(n => n.fixture.id === 105)!.y)
  })

  it('falls back safely for legacy responses or unsupported formats', () => {
    const value = stage(6)
    delete value.bracket_kind
    expect(buildBracket(value)).toBeNull()
    expect(buildBracket({ ...stage(6), bracket_kind: null })).toBeNull()
  })

  it('renders connected compact cards with explicit winner placeholders', async () => {
    useI18n().locale.value = 'en'
    const wrapper = mount(TournamentMatchesPanel, { props: { stages: { main: stage(6) } } })
    expect(wrapper.findAllComponents(TournamentBracketMatch)).toHaveLength(5)
    expect(wrapper.findAll('svg path')).toHaveLength(4)
    expect(wrapper.text()).toContain('Winner of match #104')
    expect(wrapper.get('[role="region"]').attributes('tabindex')).toBe('0')
    await wrapper.findAllComponents(TournamentBracketMatch)[0]!.get('button').trigger('click')
    expect(wrapper.emitted('select')).toEqual([[104]])
  })

  it('keeps legacy responses compact and explains why it cannot draw connections', () => {
    useI18n().locale.value = 'en'
    const legacy = stage(6)
    delete legacy.bracket_kind
    const wrapper = mount(TournamentMatchesPanel, { props: { stages: { main: legacy } } })
    expect(wrapper.findAllComponents(TournamentBracketMatch)).toHaveLength(5)
    expect(wrapper.findAll('svg path')).toHaveLength(0)
    expect(wrapper.get('[role="status"]').text()).toContain('server has not supplied the advancement links')
  })

  it('shows two compact player rows, scores and the confirmed winner', () => {
    const fixture = stage(2).levels[0]!.fixtures[0]!
    fixture.player1 = { id: 1, user_id: 1, name: 'Dana', username: 'dana' }
    fixture.player2 = { id: 2, user_id: 2, name: 'Ben', username: 'ben' }
    fixture.score1 = 5
    fixture.score2 = 2
    fixture.is_confirmed = true
    const wrapper = mount(TournamentBracketMatch, { props: { fixture } })
    expect(wrapper.findAll('.bracket-match__player')).toHaveLength(2)
    expect(wrapper.get('.is-winner').text()).toContain('Dana')
    expect(wrapper.findAll('strong').map(n => n.text())).toEqual(['5', '2'])
    expect(wrapper.get('button').attributes('aria-haspopup')).toBe('dialog')
  })
})
