import { MutationCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { errorText } from './lib/errors'
import { notify } from './lib/notify'
import { UIProvider } from './state/ui'
import './styles/index.css'

const client = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 0 } },
  mutationCache: new MutationCache({ onError: (e) => notify(errorText(e), 'error') }),
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <UIProvider><App /></UIProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
