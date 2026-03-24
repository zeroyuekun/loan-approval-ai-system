'use client'

import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { LoanApplication } from '@/types'
import { formatDate, getStatusColor } from '@/lib/utils'

interface ApplicationHeaderProps {
  application: LoanApplication
}

export function ApplicationHeader({ application }: ApplicationHeaderProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Application Information</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex justify-between">
          <span className="text-muted-foreground">ID</span>
          <span className="font-mono text-sm">{application.id}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Applicant</span>
          <Link href={`/dashboard/customers/${application.applicant.id}`} className="text-blue-600 hover:underline">
            {application.applicant.first_name} {application.applicant.last_name}
          </Link>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Status</span>
          <Badge className={getStatusColor(application.status)} variant="outline">
            {application.status.toUpperCase()}
          </Badge>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Created</span>
          <span>{formatDate(application.created_at)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">Purpose</span>
          <span className="capitalize">{application.purpose}</span>
        </div>
      </CardContent>
    </Card>
  )
}
