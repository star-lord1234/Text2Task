import { useState } from 'react'
import { useActions, useScenarios, useWorkspace } from '../api/hooks'
import type { Suggestion } from '../api/types'
import { ModeBanner } from '../components/ModeBanner'
import { ChatPanel } from '../features/chat/ChatPanel'
import { Composer } from '../features/chat/Composer'
import { DemoPlayer } from '../features/chat/DemoPlayer'
import { EditSuggestionDialog } from '../features/tasks/EditSuggestionDialog'
import { TaskPanel } from '../features/tasks/TaskPanel'
import { canDecide } from '../lib/suggest'
import { useActiveUser, useUI } from '../state/ui'

export function WorkspacePage() {
  const ws = useWorkspace()
  const sc = useScenarios()
  const ui = useUI()
  const actions = useActions()
  const people = ws.data?.participants ?? []
  const active = useActiveUser(ws.data?.participants)
  const [editing, setEditing] = useState<Suggestion | null>(null)
  const [tab, setTab] = useState<'chat' | 'tasks'>('chat')
  const busy = actions.accept.isPending || actions.dismiss.isPending || actions.patchTask.isPending
  const stepping = actions.scenarioStep.isPending || actions.scenarioPrev.isPending || actions.scenarioPlay.isPending || actions.scenarioReset.isPending || actions.loadScenario.isPending

  if (ws.isLoading) return <p className="p-6 text-sm text-muted">Loading workspace…</p>
  if (ws.isError || !ws.data) return <p role="alert" className="p-6 text-sm text-danger">Cannot load the workspace. Is the API running? {String((ws.error as Error)?.message ?? '')}</p>

  const w = ws.data
  const mine = w.suggestions.filter((s) => s.status === 'pending' && canDecide(s, active?.id)).length
  const col = (name: typeof tab) => `${tab === name ? 'flex' : 'hidden'} min-h-0 flex-col lg:flex`
  const footer = ui.mode === 'scripted'
    ? <DemoPlayer scenario={w.scenario} scenarios={sc.data?.scenarios ?? []} people={people} busy={stepping}
        onLoad={(id) => actions.loadScenario.mutate(id)} onPrev={() => actions.scenarioPrev.mutate()} onNext={() => actions.scenarioStep.mutate()}
        onPlay={() => actions.scenarioPlay.mutate()} onRestart={() => actions.scenarioReset.mutate()} />
    : <Composer people={people} active={active} mode={ui.mode} liveAvailable={w.capabilities?.modes.live ?? false} sending={actions.sendMessage.isPending}
        onSend={(b) => active && actions.sendMessage.mutate({ ...b, sender_id: active.id, mode: ui.mode })} />

  return (
    <>
      <div role="tablist" aria-label="Workspace sections" className="flex gap-1 border-b border-line bg-surface p-2 lg:hidden">
        <div className="segmented w-full [&>*]:flex-1">
          {(['chat', 'tasks'] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className="capitalize">
              {t}{t === 'tasks' && mine > 0 && <span className="ml-1.5 rounded-full bg-[#e01e5a] px-1.5 text-xs font-bold text-white">{mine}</span>}
            </button>
          ))}
        </div>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,1fr)] lg:grid-cols-[minmax(22rem,1.35fr)_minmax(22rem,1fr)]">
        <div className={col('chat')}>
          <ChatPanel messages={w.messages} people={people} tasks={w.tasks} retrying={actions.retry.isPending} onRetry={(id) => actions.retry.mutate(id)} onInspect={ui.openInspector}
            badge={<ModeBanner mode={ui.mode} caps={w.capabilities} />} footer={footer} />
        </div>
        <div className={`${col('tasks')} lg:border-l lg:border-line`}>
          <TaskPanel tasks={w.tasks} suggestions={w.suggestions} people={people} active={active} busy={busy} onOpenTask={ui.openTask} onSource={ui.openInspector}
            onAccept={(s, edits) => active && actions.accept.mutate({ id: s.id, actor_id: active.id, edits })}
            onDismiss={(s) => active && actions.dismiss.mutate({ id: s.id, actor_id: active.id })} onEdit={setEditing}
            onSwitchUser={ui.setActiveUserId}
            onComplete={(t) => active && actions.patchTask.mutate({ id: t.id, actor_id: active.id, expected_version: t.version, changes: { status: 'completed' } })} />
        </div>
      </div>
      <EditSuggestionDialog suggestion={editing} people={people} tasks={w.tasks} onClose={() => setEditing(null)}
        onSubmit={(id, edits) => { if (!active) return; actions.accept.mutate({ id, actor_id: active.id, edits }, { onSuccess: () => setEditing(null) }) }} />
    </>
  )
}
