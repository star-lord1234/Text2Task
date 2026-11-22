import { Maximize2, Network, SlidersHorizontal, Table2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useActions, useGraph, useWorkspace } from '../api/hooks'
import { Avatar } from '../components/Avatar'
import { DependencyGraph } from '../features/graph/DependencyGraph'
import { EdgeDetails } from '../features/graph/EdgeDetails'
import { GraphTable } from '../features/graph/GraphTable'
import { WhatIfPanel } from '../features/graph/WhatIfPanel'
import { notify } from '../lib/notify'
import { useActiveUser, useUI } from '../state/ui'

const HIGHLIGHTS = [['none', 'All'], ['ready', 'Ready'], ['blocked', 'Blocked'], ['review', 'Review'], ['done', 'Done']] as const

export function ExplorerPage() {
  const ws = useWorkspace()
  const ui = useUI()
  const actions = useActions()
  const people = ws.data?.participants ?? []
  const active = useActiveUser(ws.data?.participants)
  const scenario = ws.data?.scenario
  const [viewStep, setViewStep] = useState<number | null>(null)
  const graphQ = useGraph(viewStep)
  const graph = graphQ.data
  const [selNode, setSelNode] = useState<string | null>(null)
  const [selEdge, setSelEdge] = useState<string | null>(null)
  const [hiddenOwners, setHiddenOwners] = useState<Set<string>>(new Set())
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set())
  const [highlightKind, setHighlightKind] = useState<'none' | 'ready' | 'blocked' | 'review' | 'done'>('none')
  const [table, setTable] = useState(false)
  const [fit, setFit] = useState(0)
  const [pre, setPre] = useState('')
  const [dep, setDep] = useState('')
  const [whatIf, setWhatIf] = useState<{ id: string; status: string } | null>(null)

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, v: string) => { const n = new Set(set); n.has(v) ? n.delete(v) : n.add(v); setter(n) }
  const highlight = useMemo(() => {
    const out: Record<string, 'ready' | 'blocked' | 'done' | 'review'> = {}
    if (!graph) return out
    graph.nodes.forEach((n) => {
      const d = n.derived_state
      if (highlightKind === 'ready' && d === 'ready') out[n.id] = 'ready'
      if (highlightKind === 'blocked' && d === 'blocked') out[n.id] = 'blocked'
      if (highlightKind === 'review' && d === 'blocked_cancelled_prereq') out[n.id] = 'review'
      if (highlightKind === 'done' && d === 'done') out[n.id] = 'done'
    })
    return out
  }, [graph, highlightKind])

  const edge = graph?.edges.find((e) => e.id === selEdge) ?? null
  const node = graph?.nodes.find((n) => n.id === selNode) ?? null
  const busy = actions.addEdge.isPending || actions.removeEdge.isPending || actions.reconsiderEdge.isPending
  const atStep = scenario?.scenario_id ? scenario.step : null
  const historic = viewStep != null && atStep != null && viewStep !== atStep

  const add = async () => {
    if (!active || !pre || !dep) return
    const r = await actions.addEdge.mutateAsync({ actor_id: active.id, prerequisite_task_id: pre, dependent_task_id: dep, evidence: 'added manually in the explorer' })
    const d = r.decision
    if (d.status === 'rejected') notify(`Held for review: ${d.reason}`, 'error')
    else notify(`Dependency added${d.warnings?.length ? ` (${d.warnings.join(', ').toLowerCase().replace(/_/g, ' ')})` : ''}.`, 'info')
    setPre(''); setDep('')
  }

  const chip = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[13px] font-medium'
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
        <h1 className="text-[17px] font-bold">Dependencies</h1>
        <span className="hidden text-[13px] text-muted sm:inline">What has to happen before what</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-2">
        <div className="flex items-center gap-1" role="group" aria-label="Filter by owner">
          {people.map((p) => (
            <button key={p.id} aria-pressed={!hiddenOwners.has(p.id)} onClick={() => toggle(hiddenOwners, setHiddenOwners, p.id)}
              className={`${chip} ${hiddenOwners.has(p.id) ? 'text-faint line-through' : 'bg-fill'}`}><Avatar person={p} size={16} />{p.name}</button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="Highlight">
          {HIGHLIGHTS.map(([v, l]) => <button key={v} aria-pressed={highlightKind === v} onClick={() => setHighlightKind(v)}>{l}</button>)}
        </div>
        <details className="relative">
          <summary className={`${chip} cursor-pointer list-none bg-fill [&::-webkit-details-marker]:hidden`}><SlidersHorizontal size={13} aria-hidden />Show</summary>
          <fieldset className="absolute left-0 top-full z-20 mt-2 w-56 space-y-2 rounded-xl border border-line bg-surface p-3 text-sm shadow-[var(--shadow-sheet)]"><legend className="sr-only">Edge kinds</legend>
            {(['accepted', 'proposed', 'held'] as const).map((k) => (
              <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={!hiddenKinds.has(k)} onChange={() => toggle(hiddenKinds, setHiddenKinds, k)} className="accent-accent" />{k === 'held' ? 'Held for review' : k === 'proposed' ? 'Suggested' : 'Accepted'}</label>
            ))}
          </fieldset>
        </details>
        {atStep != null && atStep > 0 && (
          <label className="flex items-center gap-2 text-[13px]"><span className="text-muted">Step</span>
            <input type="range" min={0} max={atStep} value={viewStep ?? atStep} onChange={(e) => setViewStep(Number(e.target.value) === atStep ? null : Number(e.target.value))} aria-label="Scenario step shown in the graph" className="accent-accent" />
            <span data-testid="graph-step" className="tabular-nums">{viewStep ?? atStep} / {scenario?.total}</span>
          </label>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          <button className={`${chip} ${table ? 'bg-accent-bg text-accent' : 'bg-fill'}`} onClick={() => setTable((t) => !t)} aria-pressed={table}><Table2 size={13} aria-hidden />Graph as table</button>
          <button className={`${chip} bg-fill`} onClick={() => setFit((f) => f + 1)}><Maximize2 size={13} aria-hidden />Fit</button>
        </div>
      </div>

      {historic && <div role="status" className="bg-warn-bg px-4 py-1.5 text-[13px] text-warn">Showing the graph as it was at step {viewStep}. Move the slider to the latest step to edit.</div>}

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="relative min-h-64 min-w-0 flex-1 bg-surface">
          {!graph || graph.nodes.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-1 px-6 text-center text-sm text-muted">
              <Network size={36} className="mb-1 text-line-strong" aria-hidden />
              <p className="font-semibold text-ink">No tasks to connect yet</p>
              <p className="max-w-xs">Once tasks are accepted in #team-chat, the order they depend on each other shows up here.</p>
            </div>
          ) : table ? (
            <div className="h-full overflow-auto"><GraphTable graph={graph} people={people} onSelectEdge={(id) => { setSelEdge(id); setSelNode(null) }} onSelectNode={(id) => { setSelNode(id); setSelEdge(null) }} /></div>
          ) : (
            <DependencyGraph graph={graph} people={people} minimap fitKey={fit} hiddenOwners={hiddenOwners} hiddenKinds={hiddenKinds} highlight={highlight}
              selectedNode={selNode} selectedEdge={selEdge} onSelectNode={(id) => { setSelNode(id); if (id) setSelEdge(null) }} onSelectEdge={(id) => { setSelEdge(id); if (id) setSelNode(null) }} />
          )}
          {graph && graph.nodes.length > 0 && !table && (
            <div className="pointer-events-none absolute right-3 top-3 space-y-1 rounded-xl border border-line bg-surface/95 px-3 py-2 text-xs text-muted shadow-[var(--shadow-card)] backdrop-blur">
              <div className="flex items-center gap-2"><svg width="28" height="8" aria-hidden><line x1="0" y1="4" x2="28" y2="4" stroke="#1c1c1e" strokeWidth="2" /></svg>must happen first → then</div>
              <div className="flex items-center gap-2"><svg width="28" height="8" aria-hidden><line x1="0" y1="4" x2="28" y2="4" stroke="#8e8e93" strokeWidth="2" strokeDasharray="6 5" /></svg>suggested</div>
              <div className="flex items-center gap-2"><svg width="28" height="8" aria-hidden><line x1="0" y1="4" x2="28" y2="4" stroke="#c4271d" strokeWidth="2" strokeDasharray="2 4" /></svg>held for review</div>
            </div>
          )}
        </div>

        <aside aria-label="Details" className="flex max-h-[45%] w-full shrink-0 flex-col border-t border-line bg-canvas md:max-h-none md:w-80 md:border-l md:border-t-0">
          <div className="min-h-0 flex-1 overflow-y-auto">
            {graph && <EdgeDetails graph={graph} edge={edge} node={node} people={people} busy={busy || historic}
              onInspect={ui.openInspector} onOpenTask={ui.openTask}
              onRemove={(id) => active && actions.removeEdge.mutate({ id, actor_id: active.id, reason: 'removed in the explorer' })}
              onReconsider={(id) => active && actions.reconsiderEdge.mutate({ id, actor_id: active.id })} />}
            {graph && node && <WhatIfPanel graph={graph} task={node} selected={whatIf?.id === node.id ? whatIf.status : null} onSelect={(status) => setWhatIf(status ? { id: node.id, status } : null)} />}
          </div>
          {graph && graph.nodes.length >= 2 && !historic && (
            <details className="border-t border-line p-3">
              <summary className="cursor-pointer text-[13px] font-semibold text-accent">+ Add a dependency</summary>
              <form className="mt-2 space-y-2 text-[13px]" onSubmit={(e) => { e.preventDefault(); void add() }} aria-label="Add a dependency">
                <label className="block text-muted">First this…
                  <select value={pre} onChange={(e) => setPre(e.target.value)} className="field mt-1 text-ink"><option value="">Choose a task</option>{graph.nodes.map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}</select>
                </label>
                <label className="block text-muted">…then this
                  <select value={dep} onChange={(e) => setDep(e.target.value)} className="field mt-1 text-ink"><option value="">Choose a task</option>{graph.nodes.filter((n) => n.id !== pre).map((n) => <option key={n.id} value={n.id}>{n.title}</option>)}</select>
                </label>
                <button type="submit" disabled={!pre || !dep || pre === dep || busy} className="btn btn-primary btn-sm w-full">Add dependency</button>
              </form>
            </details>
          )}
        </aside>
      </div>
    </div>
  )
}
