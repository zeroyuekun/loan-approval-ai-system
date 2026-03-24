import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { Toaster } from 'sonner'
import { toast } from 'sonner'

describe('Toast integration', () => {
  it('renders Toaster component without crashing', () => {
    const { container } = render(<Toaster richColors position="top-right" />)
    expect(container).toBeTruthy()
  })

  it('toast function is callable', () => {
    expect(typeof toast).toBe('function')
    expect(typeof toast.success).toBe('function')
    expect(typeof toast.error).toBe('function')
  })
})
