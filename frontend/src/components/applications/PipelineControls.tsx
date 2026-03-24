'use client'

import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Bot, Loader2, Trash2 } from 'lucide-react'

interface PipelineControlsProps {
  applicationStatus: string
  orchestrating: boolean
  pipelineQueued: boolean
  pipelineDisabled: boolean
  pipelineError: string | null
  pipelineSuccess: string | null
  handleOrchestrate: () => void
  onDelete?: () => void
  isDeleting?: boolean
  showDeleteConfirm?: boolean
  onDeleteConfirmToggle?: (show: boolean) => void
}

export function PipelineControls({
  applicationStatus,
  orchestrating,
  pipelineQueued,
  pipelineDisabled,
  pipelineError,
  pipelineSuccess,
  handleOrchestrate,
  onDelete,
  isDeleting,
  showDeleteConfirm,
  onDeleteConfirmToggle,
}: PipelineControlsProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-6">
        <div className="flex items-center justify-center gap-4">
          <Button
            size="lg"
            onClick={handleOrchestrate}
            disabled={pipelineDisabled}
            variant={pipelineQueued ? 'outline' : 'default'}
          >
            {orchestrating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Running AI Pipeline...
              </>
            ) : pipelineQueued ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Pipeline Queued — Processing...
              </>
            ) : (
              <>
                <Bot className="mr-2 h-4 w-4" />
                {applicationStatus === 'pending' ? 'Run AI Pipeline' : 'Re-run AI Pipeline'}
              </>
            )}
          </Button>
          {onDelete && (
          !showDeleteConfirm ? (
            <Button
              variant="destructive"
              size="lg"
              onClick={() => onDeleteConfirmToggle?.(true)}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete Application
            </Button>
          ) : (
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-red-600">Are you sure?</span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onDeleteConfirmToggle?.(false)}
                disabled={isDeleting}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={onDelete}
                disabled={isDeleting}
              >
                {isDeleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
                {isDeleting ? 'Deleting...' : 'Confirm'}
              </Button>
            </div>
          )
        )}
        </div>
        {pipelineError && (
          <p className="text-sm text-red-600">{pipelineError}</p>
        )}
        {pipelineSuccess && (
          <p className="text-sm text-green-600">{pipelineSuccess}</p>
        )}
      </CardContent>
    </Card>
  )
}
