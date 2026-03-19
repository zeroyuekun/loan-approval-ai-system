'use client'

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { NextBestOffer } from '@/types'
import { formatCurrency } from '@/lib/utils'
import { Lightbulb, Mail, TrendingUp, ArrowRight } from 'lucide-react'

interface NextBestOfferCardProps {
  offer: NextBestOffer
}

function MatchIndicator({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color =
    pct >= 70 ? 'text-emerald-700 bg-emerald-50 ring-emerald-200'
    : pct >= 40 ? 'text-amber-700 bg-amber-50 ring-amber-200'
    : 'text-slate-600 bg-slate-50 ring-slate-200'

  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full ring-1 ring-inset ${color}`}>
      <TrendingUp className="h-3 w-3" />
      {pct}% match
    </span>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-dashed border-border/50 last:border-0">
      <span className="text-xs text-muted-foreground tracking-wide uppercase">{label}</span>
      <span className="text-sm font-medium tabular-nums">{value}</span>
    </div>
  )
}

export function NextBestOfferCard({ offer }: NextBestOfferCardProps) {
  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="text-base flex items-center gap-2">
          <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-amber-50 ring-1 ring-amber-200/60">
            <Lightbulb className="h-4 w-4 text-amber-600" />
          </div>
          Alternative Offers
        </CardTitle>
        {offer.analysis && (
          <CardDescription className="leading-relaxed">{offer.analysis}</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {/* Equal-height grid: each card stretches to match the tallest */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 items-stretch">
          {offer.offers.map((alt, index) => (
            <div
              key={index}
              className="group relative flex flex-col rounded-xl border border-border/60 bg-gradient-to-b from-white to-slate-50/50 shadow-soft transition-all duration-200 hover:shadow-elevated hover:-translate-y-0.5"
            >
              {/* Card header with name and match score */}
              <div className="flex items-start justify-between gap-2 p-4 pb-3">
                <h4 className="font-semibold text-sm capitalize leading-snug">
                  {alt.name || `${alt.type} Loan`}
                </h4>
                {alt.suitability_score != null && (
                  <MatchIndicator score={alt.suitability_score} />
                )}
              </div>

              {/* Financial details */}
              <div className="flex-1 px-4 pb-2">
                {alt.amount != null && (
                  <DetailRow label="Amount" value={formatCurrency(alt.amount)} />
                )}
                {alt.term_months != null && (
                  <DetailRow label="Term" value={`${alt.term_months} months`} />
                )}
                {alt.estimated_rate != null && (
                  <DetailRow label="Est. Rate" value={`${Number(alt.estimated_rate).toFixed(2)}% p.a.`} />
                )}
                {alt.monthly_repayment != null && (
                  <DetailRow label="Monthly" value={`${formatCurrency(alt.monthly_repayment)}/mo`} />
                )}
                {alt.fortnightly_repayment != null && (
                  <DetailRow label="Fortnightly" value={`${formatCurrency(alt.fortnightly_repayment)}/fn`} />
                )}
              </div>

              {/* Reasoning pinned to bottom — all cards align here */}
              <div className="mt-auto p-4 pt-3 border-t border-border/40">
                <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3">
                  {alt.reasoning}
                </p>
              </div>
            </div>
          ))}
        </div>

        {offer.marketing_message && (
          <div className="mt-6 rounded-xl border border-blue-200/60 bg-gradient-to-br from-blue-50/80 to-indigo-50/40 p-5">
            <div className="flex items-center gap-2.5 mb-3">
              <div className="flex items-center justify-center h-7 w-7 rounded-lg bg-blue-100 ring-1 ring-blue-200/60">
                <Mail className="h-3.5 w-3.5 text-blue-600" />
              </div>
              <h4 className="text-sm font-semibold text-blue-900">Customer Marketing Message</h4>
              <ArrowRight className="h-3.5 w-3.5 text-blue-400 ml-auto" />
            </div>
            <div className="text-sm text-blue-900/75 leading-relaxed whitespace-pre-line">{offer.marketing_message}</div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
