'use client'

import { useCallback, useMemo, useState } from 'react'

/**
 * Form state seeded from server data without clobbering the user's typing.
 *
 * The form is the server seed with the user's edits layered on top. A refetch
 * that changes the seed (another tab, a staff edit, a post-save invalidation)
 * updates the fields the user has not touched and leaves edited fields alone.
 * Call resetEdits() after a successful save so the form shows the saved
 * server values again.
 */
export function useSeededForm<T extends Record<string, unknown>>(seed: T | undefined) {
  const [edits, setEdits] = useState<Partial<T>>({})

  const form = useMemo(() => ({ ...(seed ?? {}), ...edits }) as Partial<T>, [seed, edits])

  const updateField = useCallback((name: string, value: unknown) => {
    setEdits((prev) => ({ ...prev, [name]: value }))
  }, [])

  const resetEdits = useCallback(() => setEdits({}), [])

  return { form, updateField, resetEdits }
}
