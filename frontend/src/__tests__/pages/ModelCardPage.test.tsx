import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/mocks/server'
import { mockModelCard } from '@/test/mocks/handlers'
import ModelCardPage from '@/app/dashboard/model-card/page'

const API_URL = 'http://localhost:8000/api/v1'

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  )
}

describe('ModelCardPage', () => {
  it('renders loading skeleton initially', () => {
    // Use a handler that never resolves
    server.use(
      http.get(`${API_URL}/ml/models/active/model-card/`, () => {
        return new Promise(() => {}) // hang forever
      }),
    )

    renderWithProviders(<ModelCardPage />)

    // Skeleton elements use animate-pulse class
    const skeletons = document.querySelectorAll('[class*="animate-pulse"]')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('renders model card with tabs when data loads', async () => {
    renderWithProviders(<ModelCardPage />)

    expect(await screen.findByRole('heading', { name: 'XGBoost Loan Approval' })).toBeInTheDocument()
    expect(screen.getByText('Overview')).toBeInTheDocument()
    expect(screen.getByText('Performance')).toBeInTheDocument()
    expect(screen.getByText('Fairness')).toBeInTheDocument()
    expect(screen.getByText('Governance')).toBeInTheDocument()
    expect(screen.getByText('Limitations')).toBeInTheDocument()
  })

  it('renders empty state when no model exists (404)', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/model-card/`, () => {
        return HttpResponse.json({ detail: 'Not found' }, { status: 404 })
      }),
    )

    renderWithProviders(<ModelCardPage />)

    expect(await screen.findByText('No active model found')).toBeInTheDocument()
    expect(screen.getByText(/Train a model first/)).toBeInTheDocument()
  })

  it('renders error state on server error', async () => {
    server.use(
      http.get(`${API_URL}/ml/models/active/model-card/`, () => {
        return HttpResponse.json({ error: 'fail' }, { status: 500 })
      }),
    )

    renderWithProviders(<ModelCardPage />)

    expect(await screen.findByText('Failed to load model card')).toBeInTheDocument()
  })

  it('displays model version and active badge', async () => {
    renderWithProviders(<ModelCardPage />)

    expect(await screen.findByText('v1.0.0')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })
})
