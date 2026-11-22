import { Background, BackgroundVariant, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useEffect, useMemo } from 'react'
import type { GraphData, GraphEdge, Participant } from '../../api/types'
import { NODE_H, NODE_W, layoutNodes } from './layout'
import { TaskNode, type TaskFlowNode } from './TaskNode'

const nodeTypes = { task: TaskNode }

type Props = {
  graph: GraphData
  people: Participant[]
  selectedNode?: string | null
  selectedEdge?: string | null
  hiddenOwners?: Set<string>
  hiddenKinds?: Set<string>
  highlight?: Record<string, 'ready' | 'blocked' | 'done' | 'review'>
  compact?: boolean
  interactive?: boolean
  minimap?: boolean
  fitKey?: string | number
  onSelectNode?: (id: string | null) => void
  onSelectEdge?: (id: string | null) => void
  height?: number | string
}

const STYLE: Record<GraphEdge['kind'], { stroke: string; dash?: string; width: number }> = {
  accepted: { stroke: '#1c1c1e', width: 2 },
  proposed: { stroke: '#8e8e93', dash: '6 5', width: 2 },
  held: { stroke: '#c4271d', dash: '2 4', width: 2 },
}

function Inner({ graph, people, selectedNode, selectedEdge, hiddenOwners, hiddenKinds, highlight, compact = false, interactive = true, minimap = false, fitKey, onSelectNode, onSelectEdge }: Props) {
  const { fitView } = useReactFlow()
  const positions = useMemo(() => layoutNodes(graph.nodes, graph.edges), [graph.nodes, graph.edges])
  const visibleNodes = useMemo(() => graph.nodes.filter((n) => !(n.owner_id && hiddenOwners?.has(n.owner_id))), [graph.nodes, hiddenOwners])
  const visibleIds = useMemo(() => new Set(visibleNodes.map((n) => n.id)), [visibleNodes])

  const nodes: TaskFlowNode[] = useMemo(() => visibleNodes.map((n) => ({
    id: n.id, type: 'task', position: positions[n.id] ?? { x: 0, y: 0 }, width: NODE_W, height: NODE_H, draggable: interactive, selectable: interactive,
    data: { node: n, owner: people.find((p) => p.id === n.owner_id) ?? null, dimmed: false, compact, highlight: selectedNode === n.id ? 'selected' : (highlight?.[n.id] ?? 'none') },
  })), [visibleNodes, positions, people, interactive, compact, selectedNode, highlight])

  const edges: Edge[] = useMemo(() => graph.edges
    .filter((e) => !e.dangling && !hiddenKinds?.has(e.kind) && visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => {
      const st = STYLE[e.kind]
      const sel = selectedEdge === e.id
      return {
        id: e.id, source: e.source, target: e.target, selected: sel, interactionWidth: 24,
        label: e.kind === 'held' ? `held: ${e.reason.split(':')[0].toLowerCase()}` : undefined,
        labelStyle: { fontSize: 11, fill: '#c4271d' }, labelBgStyle: { fill: '#fdecea' },
        style: { stroke: sel ? '#0a64d8' : st.stroke, strokeWidth: sel ? 3.5 : st.width, strokeDasharray: st.dash },
        markerEnd: { type: MarkerType.ArrowClosed, color: sel ? '#0a64d8' : st.stroke, width: 16, height: 16, markerUnits: 'userSpaceOnUse' },
        ariaLabel: `${e.source} is a prerequisite of ${e.target} (${e.kind})`,
      } as Edge
    }), [graph.edges, hiddenKinds, visibleIds, selectedEdge])

  useEffect(() => { const t = setTimeout(() => fitView({ padding: 0.18, duration: 0, maxZoom: 1.05 }), 30); return () => clearTimeout(t) }, [fitView, fitKey, graph.nodes.length, graph.edges.length])

  return (
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ maxZoom: 1.05 }} minZoom={0.2} maxZoom={1.6} proOptions={{ hideAttribution: true }}
      nodesDraggable={interactive} nodesConnectable={false} elementsSelectable={interactive} panOnDrag={interactive} zoomOnScroll={interactive}
      onNodeClick={(_, n) => onSelectNode?.(n.id)} onEdgeClick={(_, e) => onSelectEdge?.(e.id)} onPaneClick={() => { onSelectNode?.(null); onSelectEdge?.(null) }}>
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#e5e5ea" />
      {interactive && <Controls showInteractive={false} position="bottom-left" aria-label="Graph zoom controls" />}
      {minimap && <MiniMap pannable zoomable ariaLabel="Graph minimap" nodeColor={(n) => (n.data as { owner?: { color?: string } } | undefined)?.owner?.color ?? '#9aa3af'} nodeStrokeWidth={2} maskColor="rgba(242,242,247,0.7)" />}
    </ReactFlow>
  )
}

export function DependencyGraph(props: Props) {
  return (
    <div style={{ height: props.height ?? '100%', width: '100%' }} data-testid="dependency-graph">
      <ReactFlowProvider><Inner {...props} /></ReactFlowProvider>
    </div>
  )
}
