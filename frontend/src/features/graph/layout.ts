import { graphlib, layout } from '@dagrejs/dagre'
import type { GraphEdge, GraphNode } from '../../api/types'

export const NODE_W = 240
export const NODE_H = 92

export type Positions = Record<string, { x: number; y: number }>

/**
 * Left-to-right layered layout (dagre). Deterministic: nodes and edges are sorted by id first, so the same graph always lands in the same
 * place and nodes do not jump around between scenario steps. Only ACCEPTED and PROPOSED edges shape the layout; held edges are drawn but
 * never influence positions (they would otherwise reintroduce the cycle that was refused).
 */
export function layoutNodes(nodes: GraphNode[], edges: GraphEdge[], direction: 'LR' | 'TB' = 'LR'): Positions {
  const g = new graphlib.Graph()
  g.setGraph({ rankdir: direction, nodesep: 36, ranksep: 90, marginx: 20, marginy: 20 })
  g.setDefaultEdgeLabel(() => ({}))
  const key = (id: string) => ({ n: Number(id.split('-').pop()), id })
  const ordered = [...nodes].sort((a, b) => key(a.id).n - key(b.id).n || a.id.localeCompare(b.id))
  ordered.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }))
  const ids = new Set(ordered.map((n) => n.id))
  edges
    .filter((e) => e.kind !== 'held' && !e.dangling && ids.has(e.source) && ids.has(e.target))
    .sort((a, b) => a.id.localeCompare(b.id))
    .forEach((e) => g.setEdge(e.source, e.target))
  layout(g)
  const out: Positions = {}
  ordered.forEach((n) => {
    const p = g.node(n.id)
    out[n.id] = { x: Math.round(p.x - NODE_W / 2), y: Math.round(p.y - NODE_H / 2) }
  })
  return out
}
