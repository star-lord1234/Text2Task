import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Analysis, Capabilities, EvaluationData, GraphData, Impact, ScenarioInfo, ScenarioState, Settings, Suggestion, TaskDetail, Workspace } from './types'

export const keys = {
  workspace: ['workspace'] as const,
  graph: (step?: number | null) => ['graph', step ?? 'live'] as const,
  analysis: (id: string) => ['analysis', id] as const,
  task: (id: string) => ['task', id] as const,
  scenarios: ['scenarios'] as const,
  impact: (id: string, status: string) => ['impact', id, status] as const,
}

export const useWorkspace = () => useQuery({ queryKey: keys.workspace, queryFn: () => api.get<Workspace>('/api/workspace') })
export const useGraph = (step?: number | null) =>
  useQuery({ queryKey: keys.graph(step), queryFn: () => api.get<GraphData>(`/api/dependencies${step != null ? `?step=${step}` : ''}`) })
export const useAnalysis = (id: string | null) =>
  useQuery({ queryKey: keys.analysis(id ?? ''), queryFn: () => api.get<Analysis>(`/api/messages/${id}/analysis`), enabled: !!id })
export const useTask = (id: string | null) =>
  useQuery({ queryKey: keys.task(id ?? ''), queryFn: () => api.get<TaskDetail>(`/api/tasks/${id}`), enabled: !!id })
export const useScenarios = () =>
  useQuery({ queryKey: keys.scenarios, queryFn: () => api.get<{ scenarios: ScenarioInfo[]; state: ScenarioState }>('/api/scenarios') })
export const useImpact = (taskId: string | null, status: string | null) =>
  useQuery({ queryKey: keys.impact(taskId ?? '', status ?? ''), queryFn: () => api.get<Impact>(`/api/impact?task_id=${taskId}&status=${status}`), enabled: !!taskId && !!status })
export const useCapabilities = () => useQuery({ queryKey: ['capabilities'], queryFn: () => api.get<Capabilities>('/api/system/capabilities') })

/** Every write refetches the shared state; there are no WebSockets, so this keeps all panels consistent. */
export function useRefresh() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries()
}

export function useActions() {
  const refresh = useRefresh()
  const done = { onSuccess: refresh }
  return {
    sendMessage: useMutation({ mutationFn: (b: { sender_id: string; recipient_ids: string[]; text: string; mode: 'scripted' | 'live'; created_at?: string }) => api.post<Analysis>('/api/messages', b), ...done }),
    retry: useMutation({ mutationFn: (id: string) => api.post<Analysis>(`/api/messages/${id}/retry`), ...done }),
    accept: useMutation({
      mutationFn: (b: { id: string; actor_id: string; edits?: Record<string, unknown>; expected_version?: number }) =>
        api.post<{ suggestion: Suggestion }>(`/api/suggestions/${b.id}/accept`, { actor_id: b.actor_id, edits: b.edits, expected_version: b.expected_version }),
      ...done,
    }),
    dismiss: useMutation({ mutationFn: (b: { id: string; actor_id: string; reason?: string }) => api.post(`/api/suggestions/${b.id}/dismiss`, { actor_id: b.actor_id, reason: b.reason ?? '' }), ...done }),
    patchTask: useMutation({ mutationFn: (b: { id: string; actor_id: string; expected_version: number; changes: Record<string, unknown> }) => api.patch<TaskDetail>(`/api/tasks/${b.id}`, { actor_id: b.actor_id, expected_version: b.expected_version, changes: b.changes }), ...done }),
    addEdge: useMutation({ mutationFn: (b: { actor_id: string; prerequisite_task_id: string; dependent_task_id: string; evidence?: string }) => api.post<{ decision: Record<string, any>; graph: GraphData }>('/api/dependencies', b), ...done }),
    removeEdge: useMutation({ mutationFn: (b: { id: string; actor_id: string; reason?: string }) => api.del(`/api/dependencies/${b.id}?actor_id=${b.actor_id}&reason=${encodeURIComponent(b.reason ?? '')}`), ...done }),
    reconsiderEdge: useMutation({ mutationFn: (b: { id: string; actor_id: string }) => api.post(`/api/dependencies/${b.id}/reconsider`, { actor_id: b.actor_id }), ...done }),
    loadScenario: useMutation({ mutationFn: (id: string) => api.post(`/api/scenarios/${id}/load`), ...done }),
    scenarioStep: useMutation({ mutationFn: () => api.post('/api/scenarios/step'), ...done }),
    scenarioPrev: useMutation({ mutationFn: () => api.post('/api/scenarios/previous'), ...done }),
    scenarioPlay: useMutation({ mutationFn: () => api.post('/api/scenarios/play'), ...done }),
    scenarioReset: useMutation({ mutationFn: () => api.post('/api/scenarios/reset'), ...done }),
    resetWorkspace: useMutation({ mutationFn: () => api.post('/api/workspace/reset'), ...done }),
    saveSettings: useMutation({ mutationFn: (b: Partial<Settings>) => api.put<Settings>('/api/settings', b), ...done }),
  }
}

export const useEvaluation = () => useQuery({ queryKey: ['evaluation'], queryFn: () => api.get<EvaluationData>('/api/evaluation'), staleTime: Infinity })
