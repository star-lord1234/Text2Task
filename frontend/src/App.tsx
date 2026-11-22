import { Route, Routes } from 'react-router-dom'
import { useActions, useAnalysis, useCapabilities, useScenarios, useTask, useWorkspace } from './api/hooks'
import { Sidebar } from './components/Sidebar'
import { Toasts } from './components/Toasts'
import { InspectorDrawer } from './features/inspector/InspectorDrawer'
import { TaskDetails } from './features/tasks/TaskDetails'
import { canDecide } from './lib/suggest'
import { EvaluationPage } from './pages/EvaluationPage'
import { ExplorerPage } from './pages/ExplorerPage'
import { TimelinePage } from './pages/TimelinePage'
import { WorkspacePage } from './pages/WorkspacePage'
import { useActiveUser, useUI } from './state/ui'

export default function App() {
  const ws = useWorkspace()
  const caps = useCapabilities()
  const sc = useScenarios()
  const ui = useUI()
  const actions = useActions()
  const people = ws.data?.participants ?? []
  const active = useActiveUser(ws.data?.participants)
  const analysis = useAnalysis(ui.inspectorMessageId)
  const task = useTask(ui.taskId)
  const reviewCount = (ws.data?.suggestions ?? []).filter((s) => s.status === 'pending' && canDecide(s, active?.id)).length

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      <Sidebar people={people} active={active} onUser={ui.setActiveUserId} mode={ui.mode} onMode={ui.setMode} caps={caps.data ?? ws.data?.capabilities}
        scenarios={sc.data?.scenarios ?? []} scenario={ws.data?.scenario} reviewCount={reviewCount}
        onLoadScenario={(id) => { ui.setMode('scripted'); actions.loadScenario.mutate(id) }}
        onPipeline={(preset) => actions.saveSettings.mutate({ pipeline_preset: preset, refine_overrides: {} })}
        onResetWorkspace={() => actions.resetWorkspace.mutate()} />
      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-surface">
        <Routes>
          <Route path="/" element={<WorkspacePage />} />
          <Route path="/dependencies" element={<ExplorerPage />} />
          <Route path="/timeline" element={<TimelinePage />} />
          <Route path="/evaluation" element={<EvaluationPage />} />
        </Routes>
      </main>
      <InspectorDrawer open={!!ui.inspectorMessageId} analysis={analysis.data} loading={analysis.isLoading} people={people} onClose={ui.closeInspector} />
      {ui.taskId && (
        <TaskDetails task={task.data} loading={task.isLoading} people={people} tasks={ws.data?.tasks} activeId={active?.id ?? null} saving={actions.patchTask.isPending} onClose={ui.closeTask}
          onSave={(changes, v) => active && actions.patchTask.mutate({ id: ui.taskId!, actor_id: active.id, expected_version: v, changes })}
          onInspect={(id) => { ui.closeTask(); ui.openInspector(id) }} onOpenTask={ui.openTask} />
      )}
      <Toasts />
    </div>
  )
}
