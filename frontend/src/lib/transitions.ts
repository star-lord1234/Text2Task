// Mirrors ALLOWED_TRANSITIONS in src/reconciliation/models.py; the server is authoritative and re-checks every change.
export const NEXT_STATUS: Record<string, string[]> = {
  open: ['in_progress', 'completed', 'cancelled'],
  in_progress: ['completed', 'cancelled'],
  completed: [],
  cancelled: [],
}
export const LIFECYCLE_LABEL: Record<string, string> = { open: 'To do', in_progress: 'In progress', completed: 'Done', cancelled: 'Canceled' }
