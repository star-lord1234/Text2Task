import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Mode, Participant } from '../api/types'
import { onNotify } from '../lib/notify'

type Toast = { id: number; text: string; tone: 'error' | 'info' }
type UI = {
  activeUserId: string | null
  setActiveUserId: (id: string) => void
  mode: Mode
  setMode: (m: Mode) => void
  inspectorMessageId: string | null
  openInspector: (messageId: string) => void
  closeInspector: () => void
  taskId: string | null
  openTask: (id: string) => void
  closeTask: () => void
  toasts: Toast[]
  toast: (text: string, tone?: Toast['tone']) => void
  dismissToast: (id: number) => void
}

const Ctx = createContext<UI | null>(null)

function load(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
function save(key: string, v: string) {
  try { localStorage.setItem(key, v) } catch { /* private mode */ }
}

/** Persona and view state are CLIENT state only: switching user never writes to the workspace. */
export function UIProvider({ children }: { children: ReactNode }) {
  const [activeUserId, setActive] = useState<string | null>(() => load('t2t.user'))
  const [mode, setModeState] = useState<Mode>(() => (load('t2t.mode') === 'live' ? 'live' : 'scripted'))
  const [inspectorMessageId, setInspector] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [toasts, setToasts] = useState<Toast[]>([])

  const toast = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, text, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000)
  }, [])

  useEffect(() => onNotify((t, tone) => toast(t, tone)), [toast])

  const value = useMemo<UI>(() => ({
    activeUserId,
    setActiveUserId: (id) => { setActive(id); save('t2t.user', id) },
    mode,
    setMode: (m) => { setModeState(m); save('t2t.mode', m) },
    inspectorMessageId, openInspector: setInspector, closeInspector: () => setInspector(null),
    taskId, openTask: setTaskId, closeTask: () => setTaskId(null),
    toasts, toast, dismissToast: (id) => setToasts((t) => t.filter((x) => x.id !== id)),
  }), [activeUserId, mode, inspectorMessageId, taskId, toasts, toast])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useUI(): UI {
  const v = useContext(Ctx)
  if (!v) throw new Error('useUI outside UIProvider')
  return v
}

/** The effective active persona (falls back to the first participant). */
export function useActiveUser(people: Participant[] | undefined): Participant | null {
  const { activeUserId, setActiveUserId } = useUI()
  const found = people?.find((p) => p.id === activeUserId) ?? people?.[0] ?? null
  useEffect(() => { if (found && found.id !== activeUserId) setActiveUserId(found.id) }, [found, activeUserId, setActiveUserId])
  return found
}
