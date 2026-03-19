'use client'

import { ApplicationForm } from '@/components/applications/ApplicationForm'

export default function NewApplicationPage() {
  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold">New Loan Application</h2>
        <p className="text-muted-foreground mt-1">Fill in the details below to submit your loan application.</p>
      </div>
      <ApplicationForm onSuccessPath="/apply/status" />
    </div>
  )
}
