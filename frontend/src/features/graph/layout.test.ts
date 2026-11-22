import { describe, expect, it } from 'vitest'
import { edge, graph, graphNode } from '../../test/fixtures'
import { NODE_H, NODE_W, layoutNodes } from './layout'

describe('layoutNodes', () => {
  const g = graph()
  it('places prerequisites left of their dependents (left to right)', () => {
    const p = layoutNodes(g.nodes, g.edges)
    expect(p['T-1'].x).toBeLessThan(p['T-2'].x)
  })
  it('is deterministic, whatever order the nodes and edges arrive in', () => {
    const a = layoutNodes(g.nodes, g.edges)
    const b = layoutNodes([...g.nodes].reverse(), [...g.edges].reverse())
    expect(b).toEqual(a)
  })
  it('ignores held edges, so a refused cycle never moves the accepted graph', () => {
    const held = edge({ id: 'E-9', source: 'T-2', target: 'T-1', kind: 'held', status: 'rejected', reason: 'CYCLE: ...' })
    expect(layoutNodes(g.nodes, [...g.edges, held])).toEqual(layoutNodes(g.nodes, g.edges))
  })
  it('handles zero and one node', () => {
    expect(layoutNodes([], [])).toEqual({})
    expect(Object.keys(layoutNodes([graphNode({})], []))).toEqual(['T-1'])
  })
  it('never overlaps nodes, even for a larger graph', () => {
    const nodes = Array.from({ length: 40 }, (_, i) => graphNode({ id: `T-${i + 1}`, title: `task ${i + 1}` }))
    const edges = nodes.slice(1).map((n, i) => edge({ id: `E-${i}`, source: `T-${Math.floor(i / 2) + 1}`, target: n.id }))
    const p = layoutNodes(nodes, edges)
    const boxes = Object.values(p)
    for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
      const overlap = boxes[i].x < boxes[j].x + NODE_W && boxes[j].x < boxes[i].x + NODE_W && boxes[i].y < boxes[j].y + NODE_H && boxes[j].y < boxes[i].y + NODE_H
      expect(overlap).toBe(false)
    }
  })
  it('ignores dangling edges to unknown tasks', () => {
    expect(() => layoutNodes(g.nodes, [...g.edges, edge({ id: 'E-x', source: 'T-1', target: 'T-99', dangling: true })])).not.toThrow()
  })
})
