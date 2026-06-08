'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { DecisionReview } from '@/types'

export function useRequestDecisionReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (vars: { application: string; reason: string }) => {
      const { data } = await api.post<DecisionReview>('/loans/decision-reviews/', vars)
      return data
    },
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['decision-review', vars.application] })
    },
  })
}

export function useDecisionReview(applicationId: string) {
  return useQuery({
    queryKey: ['decision-review', applicationId],
    queryFn: async () => {
      const { data } = await api.get<{ results: DecisionReview[] } | DecisionReview[]>(
        '/loans/decision-reviews/',
        { params: { application: applicationId } },
      )
      const list = Array.isArray(data) ? data : (data.results ?? [])
      return list.find((r) => r.application === applicationId) ?? list[0] ?? null
    },
  })
}
