'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { NextBestOffer } from '@/types'
import { formatCurrency } from '@/lib/utils'
import { Lightbulb } from 'lucide-react'

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
                <h4 className="font-semibold text-sm capitalize">{alt.type} Loan</h4>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Amount</span>
                    <span className="font-medium">{formatCurrency(alt.amount)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Term</span>
                    <span>{alt.term_months} months</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Est. Rate</span>
                    <span>{alt.estimated_rate.toFixed(2)}%</span>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground pt-1 border-t">{alt.reasoning}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
