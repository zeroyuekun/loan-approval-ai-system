import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PipelineControls } from '@/components/applications/PipelineControls'

const defaultProps = {
  applicationStatus: 'pending',
  orchestrating: false,
  pipelineQueued: false,
  pipelineDisabled: false,
  pipelineError: null,
  pipelineSuccess: null,
  handleOrchestrate: vi.fn(),
}

describe('PipelineControls', () => {
  it('shows "Run AI Pipeline" for pending status', () => {
    render(<PipelineControls {...defaultProps} applicationStatus="pending" />)
    expect(screen.getByText('Run AI Pipeline')).toBeInTheDocument()
  })

  it('shows "Re-run AI Pipeline" for non-pending status', () => {
    render(<PipelineControls {...defaultProps} applicationStatus="approved" />)
    expect(screen.getByText('Re-run AI Pipeline')).toBeInTheDocument()
  })

  it('shows "Running AI Pipeline..." when orchestrating', () => {
    render(<PipelineControls {...defaultProps} orchestrating={true} pipelineDisabled={true} />)
    expect(screen.getByText('Running AI Pipeline...')).toBeInTheDocument()
  })

  it('shows "Pipeline Queued — Processing..." when pipelineQueued', () => {
    render(<PipelineControls {...defaultProps} pipelineQueued={true} pipelineDisabled={true} />)
    expect(screen.getByText('Pipeline Queued — Processing...')).toBeInTheDocument()
  })

  it('disables button when pipelineDisabled is true', () => {
    render(<PipelineControls {...defaultProps} pipelineDisabled={true} />)
    const button = screen.getByRole('button', { name: /pipeline/i })
    expect(button).toBeDisabled()
  })

  it('calls handleOrchestrate on button click', async () => {
    const handleOrchestrate = vi.fn()
    const user = userEvent.setup()
    render(<PipelineControls {...defaultProps} handleOrchestrate={handleOrchestrate} />)
    await user.click(screen.getByRole('button', { name: /Run AI Pipeline/i }))
    expect(handleOrchestrate).toHaveBeenCalledTimes(1)
  })

  it('shows error message when pipelineError is set', () => {
    render(<PipelineControls {...defaultProps} pipelineError="Something went wrong" />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('shows success message when pipelineSuccess is set', () => {
    render(<PipelineControls {...defaultProps} pipelineSuccess="Pipeline completed" />)
    expect(screen.getByText('Pipeline completed')).toBeInTheDocument()
  })

  it('shows "Delete Application" button when onDelete is provided', () => {
    render(<PipelineControls {...defaultProps} onDelete={vi.fn()} showDeleteConfirm={false} onDeleteConfirmToggle={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Delete Application/i })).toBeInTheDocument()
  })

  it('hides delete button when onDelete is not provided', () => {
    render(<PipelineControls {...defaultProps} />)
    expect(screen.queryByRole('button', { name: /Delete Application/i })).not.toBeInTheDocument()
  })

  it('shows confirmation dialog when showDeleteConfirm is true', () => {
    render(<PipelineControls {...defaultProps} onDelete={vi.fn()} showDeleteConfirm={true} onDeleteConfirmToggle={vi.fn()} />)
    expect(screen.getByText('Are you sure?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Confirm/i })).toBeInTheDocument()
  })

  it('calls onDeleteConfirmToggle(true) when delete button clicked', async () => {
    const onDeleteConfirmToggle = vi.fn()
    const user = userEvent.setup()
    render(<PipelineControls {...defaultProps} onDelete={vi.fn()} showDeleteConfirm={false} onDeleteConfirmToggle={onDeleteConfirmToggle} />)
    await user.click(screen.getByRole('button', { name: /Delete Application/i }))
    expect(onDeleteConfirmToggle).toHaveBeenCalledWith(true)
  })

  it('calls onDeleteConfirmToggle(false) when cancel clicked', async () => {
    const onDeleteConfirmToggle = vi.fn()
    const user = userEvent.setup()
    render(<PipelineControls {...defaultProps} onDelete={vi.fn()} showDeleteConfirm={true} onDeleteConfirmToggle={onDeleteConfirmToggle} />)
    await user.click(screen.getByRole('button', { name: /Cancel/i }))
    expect(onDeleteConfirmToggle).toHaveBeenCalledWith(false)
  })

  it('calls onDelete when confirm clicked', async () => {
    const onDelete = vi.fn()
    const user = userEvent.setup()
    render(<PipelineControls {...defaultProps} onDelete={onDelete} showDeleteConfirm={true} onDeleteConfirmToggle={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: /Confirm/i }))
    expect(onDelete).toHaveBeenCalledTimes(1)
  })

  it('shows loading state when isDeleting', () => {
    render(<PipelineControls {...defaultProps} onDelete={vi.fn()} showDeleteConfirm={true} onDeleteConfirmToggle={vi.fn()} isDeleting={true} />)
    expect(screen.getByText('Deleting...')).toBeInTheDocument()
    // Cancel and confirm buttons should be disabled
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Deleting/i })).toBeDisabled()
  })
})
