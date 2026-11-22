// Tiny pub/sub so non-React code (the query client's mutation error handler) can raise a toast.
type Fn = (text: string, tone: 'error' | 'info') => void
let listener: Fn | null = null
export const onNotify = (fn: Fn) => { listener = fn; return () => { if (listener === fn) listener = null } }
export const notify: Fn = (t, tone) => listener?.(t, tone)
