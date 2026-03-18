'use client'

import Link from 'next/link'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { LoanApplication } from '@/types'
import { formatCurrency, formatDate, getStatusColor } from '@/lib/utils'

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
            </TableRow>
          </TableHeader>
          <TableBody>
            {applications.slice(0, 5).map((app) => (
              <TableRow key={app.id}>
                <TableCell>
                  <Link href={`/dashboard/customers/${app.applicant.id}`} className="font-medium text-blue-600 hover:underline">
                    {app.applicant.first_name} {app.applicant.last_name}
                  </Link>
                </TableCell>
                <TableCell>{formatCurrency(app.loan_amount)}</TableCell>
                <TableCell>
                  <Badge className={getStatusColor(app.status)} variant="outline">
                    {app.status.toUpperCase()}
                  </Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{formatDate(app.created_at)}</TableCell>
              </TableRow>
            ))}
            {applications.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground">
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
