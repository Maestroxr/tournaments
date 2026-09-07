import type { TournamentFixture, TournamentProgressStage } from '@/types/tournamentProgress'

export const BRACKET_CARD_WIDTH = 216
export const BRACKET_CARD_HEIGHT = 62
const GAP = 56
const ROW = 116
const HEADER = 44

export function buildBracket(stage: TournamentProgressStage) {
  const fixtures = stage.levels.flatMap(level => level.fixtures)
  // Only connect authoritative single-elimination positions; never infer links from array order.
  if (stage.bracket_kind !== 'single_elimination' || !fixtures.length || fixtures.some(f =>
    !f.bracket || !Number.isSafeInteger(f.bracket.position) || f.bracket.position < 1 || f.bracket.position > 4095,
  )) return null
  if (new Set(fixtures.map(f => f.bracket!.position)).size !== fixtures.length) return null
  const maxDepth = Math.floor(Math.log2(Math.max(...fixtures.map(f => f.bracket!.position))))
  const nodes = fixtures.map(fixture => {
    const position = fixture.bracket!.position
    const depth = Math.floor(Math.log2(position))
    const column = maxDepth - depth
    const center = HEADER + (position - 2 ** depth + .5) * 2 ** column * ROW
    return { fixture, x: column * (BRACKET_CARD_WIDTH + GAP), y: center - BRACKET_CARD_HEIGHT / 2, center, column }
  })
  const byId = new Map(nodes.map(node => [node.fixture.id, node]))
  const sources = new Map<number, Partial<Record<1 | 2, TournamentFixture>>>()
  const edges: Array<{ from: number; to: number; path: string }> = []
  for (const node of nodes) {
    const destination = node.fixture.bracket!.winner_to
    if (!destination) continue
    const target = byId.get(destination.fixture_id)
    if (!target || target.column <= node.column || ![1, 2].includes(destination.player_slot)) return null
    const entries = sources.get(target.fixture.id) ?? {}
    const slot = destination.player_slot as 1 | 2
    if (entries[slot]) return null
    entries[slot] = node.fixture
    sources.set(target.fixture.id, entries)
    const fromX = node.x + BRACKET_CARD_WIDTH
    const bend = fromX + GAP / 2
    edges.push({ from: node.fixture.id, to: target.fixture.id,
      path: `M ${fromX} ${node.center} H ${bend} V ${target.center} H ${target.x}` })
  }
  return { nodes, edges, sources, width: (maxDepth + 1) * (BRACKET_CARD_WIDTH + GAP) - GAP,
    height: HEADER + 2 ** maxDepth * ROW,
    columns: Array.from({ length: maxDepth + 1 }, (_, index) => ({
      x: index * (BRACKET_CARD_WIDTH + GAP), name: stage.levels[index]?.name,
    })),
  }
}
