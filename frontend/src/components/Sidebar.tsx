import * as Dialog from '@radix-ui/react-dialog'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import { BarChart3, CalendarRange, Check, ChevronsUpDown, Hash, Network, Settings, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import type { Capabilities, Mode, Participant, ScenarioInfo, ScenarioState } from '../api/types'
import { Avatar } from './Avatar'

export type ShellProps = {
  people: Participant[]
  active: Participant | null
  onUser: (id: string) => void
  mode: Mode
  onMode: (m: Mode) => void
  caps: Capabilities | undefined
  scenarios: ScenarioInfo[]
  scenario: ScenarioState | undefined
  onLoadScenario: (id: string) => void
  onPipeline?: (preset: string) => void
  onResetWorkspace: () => void
  reviewCount: number
}

const NAV = [
  { to: '/', label: 'team-chat', icon: Hash, end: true },
  { to: '/dependencies', label: 'Dependencies', icon: Network },
  { to: '/timeline', label: 'Timeline', icon: CalendarRange },
  { to: '/evaluation', label: 'Model results', icon: BarChart3 },
]

/** Slack-style workspace sidebar (desktop) that becomes a compact top bar on phones. */
export function Sidebar(p: ShellProps) {
  return (
    <>
      <aside aria-label="Workspace" className="hidden w-60 shrink-0 flex-col bg-sidebar text-sidebar-ink md:flex">
        <div className="px-4 pb-3 pt-4">
          <div className="text-[17px] font-bold tracking-tight text-white">Text2Task</div>
          <div className="text-xs text-sidebar-muted">Turns team chat into tasks</div>
        </div>
        <nav aria-label="Main" className="flex flex-col gap-0.5 px-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => `flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[15px] ${isActive ? 'bg-sidebar-active font-semibold text-white' : 'hover:bg-sidebar-hover'}`}>
              <Icon size={16} aria-hidden className="opacity-80" />
              <span className="flex-1">{label}</span>
              {to === '/' && p.reviewCount > 0 && <span className="rounded-full bg-[#e01e5a] px-1.5 text-xs font-bold text-white" aria-label={`${p.reviewCount} waiting for you`}>{p.reviewCount}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-1 border-t border-white/10 p-2">
          <SettingsSheet {...p} trigger={<button className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[15px] hover:bg-sidebar-hover"><Settings size={16} aria-hidden className="opacity-80" />Settings</button>} />
          <UserMenu {...p} />
        </div>
      </aside>

      <header className="flex items-center gap-1 bg-sidebar px-3 py-2 text-sidebar-ink md:hidden">
        <span className="mr-1 font-bold text-white">Text2Task</span>
        <nav aria-label="Main" className="flex flex-1 items-center gap-0.5 overflow-x-auto">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} aria-label={label} title={label}
              className={({ isActive }) => `relative rounded-md p-2 ${isActive ? 'bg-sidebar-active text-white' : 'hover:bg-sidebar-hover'}`}>
              <Icon size={18} aria-hidden />
              {to === '/' && p.reviewCount > 0 && <span aria-hidden className="absolute right-0.5 top-0.5 h-2 w-2 rounded-full bg-[#e01e5a]" />}
            </NavLink>
          ))}
        </nav>
        <SettingsSheet {...p} trigger={<button aria-label="Settings" className="rounded-md p-2 hover:bg-sidebar-hover"><Settings size={18} aria-hidden /></button>} />
        <UserMenu {...p} compact />
      </header>
    </>
  )
}

function UserMenu({ people, active, onUser, compact }: ShellProps & { compact?: boolean }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger aria-label={`Viewing as ${active?.name ?? 'nobody'}. Switch person`}
        className={compact ? 'rounded-md p-1 hover:bg-sidebar-hover' : 'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-sidebar-hover'}>
        <Avatar person={active} size={compact ? 26 : 30} />
        {!compact && (
          <>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-[15px] font-semibold text-white">{active?.name ?? '…'}</span>
              <span className="block truncate text-xs text-sidebar-muted">{active?.role}</span>
            </span>
            <ChevronsUpDown size={14} aria-hidden className="opacity-70" />
          </>
        )}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="start" side="top" sideOffset={8} className="z-50 min-w-60 rounded-xl border border-line bg-surface p-1.5 text-[15px] shadow-[var(--shadow-sheet)]">
          <DropdownMenu.Label className="px-2.5 pb-1 pt-1.5 text-xs text-faint">View the app as… (demo switch, not a login)</DropdownMenu.Label>
          <DropdownMenu.RadioGroup value={active?.id} onValueChange={onUser}>
            {people.map((p) => (
              <DropdownMenu.RadioItem key={p.id} value={p.id} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 outline-none data-[highlighted]:bg-fill">
                <Avatar person={p} size={26} />
                <span className="flex-1 leading-tight"><span className="block font-medium">{p.name}</span><span className="block text-xs text-faint">{p.role}</span></span>
                <DropdownMenu.ItemIndicator><Check size={16} className="text-accent" aria-hidden /></DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

function SettingsSheet({ mode, onMode, caps, scenarios, scenario, onLoadScenario, onPipeline, onResetWorkspace, trigger }: ShellProps & { trigger: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)
  const liveOk = caps?.modes.live ?? false
  const preset = caps?.pipeline.preset.split('+')[0] ?? ''
  return (
    <Dialog.Root open={open} onOpenChange={(o) => { setOpen(o); setConfirmReset(false) }}>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content aria-describedby={undefined} className="enter fixed left-1/2 top-1/2 z-50 max-h-[88vh] w-[min(28rem,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl bg-canvas p-4 text-ink shadow-[var(--shadow-sheet)] focus:outline-none">
          <div className="mb-3 flex items-center">
            <Dialog.Title className="flex-1 text-[17px] font-semibold">Settings</Dialog.Title>
            <Dialog.Close aria-label="Close settings" className="rounded-full bg-line p-1 text-muted hover:text-ink"><X size={16} /></Dialog.Close>
          </div>

          <p className="section-label mb-1.5 px-1">How messages are read</p>
          <div className="group-list mb-1 p-3">
            <ToggleGroup.Root type="single" value={mode} aria-label="Mode" onValueChange={(v) => v && onMode(v as Mode)} className="segmented w-full [&>*]:flex-1">
              <ToggleGroup.Item value="scripted">Demo story</ToggleGroup.Item>
              <ToggleGroup.Item value="live" disabled={!liveOk} title={liveOk ? 'Real models' : (caps?.modes.live_reason ?? 'Model unavailable')}>Live AI</ToggleGroup.Item>
            </ToggleGroup.Root>
          </div>
          <p className="mb-4 px-1 text-xs text-faint">
            {mode === 'scripted' ? 'Replays a short pre-written conversation step by step.' : liveOk ? 'You type messages; the trained models read them.' : (caps?.modes.live_reason ?? 'The models are not available.')}
          </p>

          {mode === 'scripted' ? (
            <>
              <p className="section-label mb-1.5 px-1">Demo story</p>
              <div role="radiogroup" aria-label="Scenario" className="group-list mb-4">
                {scenarios.map((s) => {
                  const on = scenario?.scenario_id === s.id
                  return (
                    <button key={s.id} role="radio" aria-checked={on} onClick={() => { onLoadScenario(s.id); setOpen(false) }} className="flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-fill">
                      <span className="min-w-0 flex-1"><span className="block font-medium">{s.title.replace(/^Scenario \w+ — /, '')}</span><span className="block text-xs text-faint">{s.steps} messages</span></span>
                      {on && <Check size={18} className="mt-0.5 text-accent" aria-hidden />}
                    </button>
                  )
                })}
              </div>
            </>
          ) : caps && (
            <>
              <p className="section-label mb-1.5 px-1">AI pipeline</p>
              <div className="group-list mb-1 p-3">
                <select aria-label="Pipeline" value={preset} onChange={(e) => onPipeline?.(e.target.value)} className="field">
                  {caps.pipeline.presets.map((p) => <option key={p.name} value={p.name}>{p.name.replace(/_/g, ' ')}</option>)}
                </select>
              </div>
              <p className="mb-4 px-1 text-xs text-faint">{caps.pipeline.presets.find((p) => p.name === preset)?.note}</p>
            </>
          )}

          <div className="group-list">
            {!confirmReset
              ? <button className="w-full px-3 py-2.5 text-left font-medium text-danger hover:bg-fill" onClick={() => setConfirmReset(true)}>Reset workspace…</button>
              : (
                <div className="flex items-center gap-2 px-3 py-2.5">
                  <span className="flex-1 text-sm">Delete all messages and tasks?</span>
                  <button className="btn btn-gray btn-sm" onClick={() => setConfirmReset(false)}>Cancel</button>
                  <button className="btn btn-sm bg-danger text-white" onClick={() => { onResetWorkspace(); setOpen(false) }}>Reset</button>
                </div>
              )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
