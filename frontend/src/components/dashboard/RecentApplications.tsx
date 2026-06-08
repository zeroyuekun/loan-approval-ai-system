'use client'

import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { LoanApplication } from '@/types'
import { formatCurrency, formatDate, getDisplayStatus } from '@/lib/utils'

interface RecentApplicationsProps {
  applications: LoanApplication[]
}

export function RecentApplications({ applications }: RecentApplicationsProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent Applications</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Applicant</TableHead>
              <TableHead>Amount</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Date</TableHead>
              <TableHead className="sr-only">Open</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {applications.slice(0, 5).map((app) => {
              const s = getDisplayStatus(app.status, app.decision)
              return (
                <TableRow key={app.id} className="hover:bg-muted/50">
                  <TableCell>
                    <Link
                      href={`/dashboard/customers/${app.applicant.id}`}
                      className="font-medium text-blue-600 hover:underline"
                    >
                      {app.applicant.first_name} {app.applicant.last_name}
                    </Link>
                  </TableCell>
                  <TableCell>{formatCurrency(app.loan_amount)}</TableCell>
                  <TableCell>
                    <Badge className={s.color} variant="outline">{s.label}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{formatDate(app.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <Link
                      href={`/dashboard/applications/${app.id}`}
                      aria-label={`Open application ${app.id}`}
                      className="text-xs text-blue-600 hover:underline"
                    >
                      Open →
                    </Link>
                  </TableCell>
                </TableRow>
              )
            })}
            {applications.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground">
                  No applications yet
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
