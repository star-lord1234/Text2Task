import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { edge, graph, graphNode, people } from '../../test/fixtures'
import { DependencyGraph } from './DependencyGraph'

describe('DependencyGraph renders without errors for zero, one and many nodes', () => {
  it('zero nodes', () => {
    render(<DependencyGraph graph={graph([], [])} people={people} />)
    expect(screen.getByTestId('dependency-graph')).toBeInTheDocument()
  })
  it('one node, showing owner and a status label (not colour alone)', () => {
    render(<DependencyGraph graph={graph([graphNode({})], [])} people={people} />)
    const n = screen.getByTestId('node-T-1')
    expect(n).toHaveTextContent('prepare the cleaned dataset')
    expect(n).toHaveTextContent('Anushree')
    expect(n).toHaveTextContent('To do')
    expect(n.querySelector('svg')).toBeTruthy()
  })
  it('a blocked dependent shows Blocked and its prerequisite state', () => {
    render(<DependencyGraph graph={graph()} people={people} />)
    expect(screen.getByTestId('node-T-2')).toHaveAttribute('data-state', 'blocked')
    expect(screen.getByTestId('node-T-2')).toHaveTextContent('Blocked')
  })
  it('many nodes', () => {
    const nodes = Array.from({ length: 60 }, (_, i) => graphNode({ id: `T-${i + 1}`, title: `task ${i + 1}`, owner_id: people[i % 3].id }))
    const edges = nodes.slice(1).map((n, i) => edge({ id: `E-${i}`, source: `T-${i + 1}`, target: n.id }))
    render(<DependencyGraph graph={graph(nodes, edges)} people={people} />)
    expect(screen.getByTestId('node-T-1')).toBeInTheDocument()
  })
  it('filtering an owner removes that owner\'s nodes', () => {
    render(<DependencyGraph graph={graph()} people={people} hiddenOwners={new Set(['bianca'])} />)
    expect(screen.queryByTestId('node-T-2')).not.toBeInTheDocument()
    expect(screen.getByTestId('node-T-1')).toBeInTheDocument()
  })
})
