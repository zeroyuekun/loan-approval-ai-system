'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface ForceRerunDialogProps {
  open: boolean
  /** Called when the user dismisses the dialog (Cancel, close button, backdrop). */
  onCancel: () => void
  /** Called with the trimmed, non-empty reason the user typed. */
  onConfirm: (reason: string) => void
  isPending: boolean
  error: string | null
  description?: string
}

/**
 * Confirmation for a forced pipeline re-run. The backend writes the reason to
 * the audit log, so it must be typed by the person forcing the run, never
 * filled in by the UI. Shared by the Human Review queue and the application
 * detail page.
 */
export function ForceRerunDialog(props: ForceRerunDialogProps) {
  // Mounted only while open, so the typed reason never carries over to the
  // next forced run.
  return props.open ? <ForceRerunDialogBody {...props} /> : null
}

function ForceRerunDialogBody({
  onCancel,
  onConfirm,
  isPending,
  error,
  description = 'This generates a new decision and a new customer email. A reason is required and the action is audited.',
}: ForceRerunDialogProps) {
  const [reason, setReason] = useState('')

  const cancel = () => {
    if (isPending) return
    onCancel()
  }

  return (
    <Dialog open onOpenChange={(o) => { if (!o) cancel() }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Force pipeline rerun</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <label htmlFor="force-rerun-reason" className="sr-only">
          Reason for forced rerun
        </label>
        <textarea
          id="force-rerun-reason"
          className="w-full min-h-[80px] rounded-md border border-slate-200 bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="Reason (required) — e.g. bias flag resolved, model retrained"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          disabled={isPending}
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={cancel} disabled={isPending}>
            Cancel
          </Button>
          <Button onClick={() => onConfirm(reason.trim())} disabled={!reason.trim() || isPending}>
            {isPending ? 'Submitting…' : 'Confirm force rerun'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
