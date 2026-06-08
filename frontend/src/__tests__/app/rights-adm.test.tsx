import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ConsumerRightsPage from '@/app/rights/page'

describe('rights page ADM disclosure', () => {
  it('discloses automated decision-making and the right to human review', () => {
    render(<ConsumerRightsPage />)
    expect(screen.getByText(/automated decision-making/i)).toBeInTheDocument()
    expect(screen.getByText(/request a human review/i)).toBeInTheDocument()
  })
})
