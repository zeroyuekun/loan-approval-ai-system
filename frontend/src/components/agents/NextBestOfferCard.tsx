'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { NextBestOffer } from '@/types'
import { formatCurrency } from '@/lib/utils'
import { Lightbulb, Mail } from 'lucide-react'

interface NextBestOfferCardProps {
  offer: NextBestOffer
}

export function NextBestOfferCard({ offer }: NextBestOfferCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-yellow-600" />
          Alternative Offers
        </CardTitle>
        {offer.analysis && (
          <CardDescription>{offer.analysis}</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {offer.offers.map((alt, index) => (
            <Card key={index} className="border-dashed">
              <CardContent className="pt-4 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="font-semibold text-sm capitalize">{alt.name || `${alt.type} Loan`}</h4>
                  {alt.suitability_score != null && (
                    <span className="text-xs font-medium text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded">
                      {Math.round(alt.suitability_score * 100)}% match
                    </span>
                  )}
                </div>
                <div className="space-y-1 text-sm">
                  {alt.amount != null && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Amount</span>
                      <span className="font-medium">{formatCurrency(alt.amount)}</span>
                    </div>
                  )}
                  {alt.term_months != null && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Term</span>
                      <span>{alt.term_months} months</span>
                    </div>
                  )}
                  {alt.estimated_rate != null && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Est. Rate</span>
                      <span>{Number(alt.estimated_rate).toFixed(2)}% p.a.</span>
                    </div>
                  )}
                  {alt.monthly_repayment != null && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Monthly</span>
                      <span>{formatCurrency(alt.monthly_repayment)}/mo</span>
                    </div>
                  )}
                  {alt.fortnightly_repayment != null && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Fortnightly</span>
                      <span>{formatCurrency(alt.fortnightly_repayment)}/fn</span>
                    </div>
                  )}
                </div>
                <p className="text-xs text-muted-foreground pt-1 border-t">{alt.reasoning}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        {offer.marketing_message && (
          <div className="mt-6 rounded-lg border bg-blue-50/50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Mail className="h-4 w-4 text-blue-600" />
              <h4 className="text-sm font-semibold text-blue-900">Customer Marketing Message</h4>
            </div>
            <div className="text-sm text-blue-900/80 whitespace-pre-line">{offer.marketing_message}</div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
