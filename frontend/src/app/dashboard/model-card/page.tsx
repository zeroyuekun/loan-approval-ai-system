'use client'

import { useModelCard } from '@/hooks/useModelCard'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { XCircle, FileText, AlertTriangle, CheckCircle2, Clock, Shield } from 'lucide-react'

function formatMetric(value: number | null | undefined, decimals = 4): string {
  if (value == null) return '\u2014'
  return value.toFixed(decimals)
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return '\u2014'
  return `${(value * 100).toFixed(2)}%`
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '\u2014'
  return new Date(iso).toLocaleDateString('en-AU', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function KeyValue({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-4 px-6 py-2.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm text-right ${mono ? 'font-mono tabular-nums' : ''}`}>
        {value}
      </span>
    </div>
  )
}

export default function ModelCardPage() {
  const { data: card, isLoading, isError } = useModelCard()

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid gap-6 md:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <XCircle className="h-12 w-12 mx-auto text-red-400" />
          <p className="text-muted-foreground">Failed to load model card</p>
          <p className="text-sm text-muted-foreground">Check that the backend is running and try refreshing the page.</p>
        </div>
      </div>
    )
  }

  if (!card) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="text-center space-y-2">
          <FileText className="h-12 w-12 mx-auto text-muted-foreground" />
          <p className="text-muted-foreground">No active model found</p>
          <p className="text-sm text-muted-foreground">Train a model first to generate a model card.</p>
        </div>
      </div>
    )
  }

  const { model_details, intended_use, training_data, performance_metrics, fairness_analysis, governance, independent_validation, limitations, synthetic_data_validation, regulatory_compliance, last_updated } = card

  const algorithmLabels: Record<string, string> = { rf: 'Random Forest', xgb: 'XGBoost' }
  const algorithmLabel = algorithmLabels[model_details.algorithm] || model_details.algorithm

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">{model_details.name}</h3>
          <Badge variant="secondary" className="text-sm px-3 py-0.5">v{model_details.version}</Badge>
          <Badge variant={governance.status === 'active' ? 'success' : 'destructive'} className="text-sm px-3 py-0.5">
            {governance.status === 'active' ? 'Active' : 'Retired'}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Last updated {formatDate(last_updated)}
        </p>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="performance">Performance</TabsTrigger>
          <TabsTrigger value="fairness">Fairness</TabsTrigger>
          <TabsTrigger value="governance">Governance</TabsTrigger>
          <TabsTrigger value="limitations">Limitations</TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview">
          <div className="grid gap-6 md:grid-cols-2 mt-4">
            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Model Details</CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <div className="divide-y divide-border">
                  <KeyValue label="Name" value={model_details.name} />
                  <KeyValue label="Algorithm" value={algorithmLabel} />
                  <KeyValue label="Version" value={model_details.version} mono />
                  <KeyValue label="Created" value={formatDate(model_details.created_at)} />
                  <KeyValue label="Description" value={model_details.description} />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Intended Use</CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <div className="divide-y divide-border">
                  <KeyValue label="Primary Use" value={intended_use.primary_use} />
                  <KeyValue label="Users" value={intended_use.users} />
                  <KeyValue label="Out of Scope" value={intended_use.out_of_scope} />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Training Data</CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <div className="divide-y divide-border">
                  <KeyValue label="Description" value={training_data.description} />
                  <KeyValue label="Dataset Size" value={training_data.size > 0 ? training_data.size.toLocaleString() : '\u2014'} mono />
                  <KeyValue label="Features" value={training_data.features > 0 ? training_data.features.toLocaleString() : '\u2014'} mono />
                  {Object.entries(training_data.label_distribution).map(([label, ratio]) => (
                    <KeyValue key={label} label={`Class: ${label}`} value={formatPercent(ratio)} mono />
                  ))}
                </div>
              </CardContent>
            </Card>

            {synthetic_data_validation.status === 'available' && (
              <Card>
                <CardHeader className="pb-4">
                  <CardTitle className="text-base">Synthetic Data Validation</CardTitle>
                  <CardDescription>TSTR (Train on Synthetic, Test on Real) estimates</CardDescription>
                </CardHeader>
                <CardContent className="px-0">
                  <div className="divide-y divide-border">
                    <KeyValue label="Est. Real-World AUC" value={formatMetric(synthetic_data_validation.estimated_real_world_auc)} mono />
                    {synthetic_data_validation.estimated_auc_range && (
                      <KeyValue label="AUC Range" value={`${synthetic_data_validation.estimated_auc_range[0].toFixed(2)} \u2013 ${synthetic_data_validation.estimated_auc_range[1].toFixed(2)}`} mono />
                    )}
                    <KeyValue label="Degradation" value={synthetic_data_validation.degradation_from_synthetic != null ? formatPercent(synthetic_data_validation.degradation_from_synthetic) : '\u2014'} mono />
                    <KeyValue label="Confidence Score" value={formatMetric(synthetic_data_validation.synthetic_confidence_score, 2)} mono />
                    {synthetic_data_validation.confidence_interpretation && (
                      <KeyValue label="Interpretation" value={synthetic_data_validation.confidence_interpretation} />
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* Performance Tab */}
        <TabsContent value="performance">
          <div className="space-y-6 mt-4">
            <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
              {[
                { label: 'Accuracy', value: performance_metrics.accuracy, pct: true },
                { label: 'Precision', value: performance_metrics.precision, pct: true },
                { label: 'Recall', value: performance_metrics.recall, pct: true },
                { label: 'F1 Score', value: performance_metrics.f1_score, pct: true },
                { label: 'AUC-ROC', value: performance_metrics.auc_roc, pct: true },
                { label: 'Gini', value: performance_metrics.gini, pct: false },
                { label: 'Brier Score', value: performance_metrics.brier_score, pct: false },
                { label: 'ECE', value: performance_metrics.ece, pct: false },
              ].filter(m => m.value != null).map((m) => (
                <Card key={m.label}>
                  <CardContent className="pt-5 pb-4">
                    <p className="text-xs font-medium text-muted-foreground mb-1.5">{m.label}</p>
                    <p className="text-2xl font-bold tabular-nums">
                      {m.pct ? formatPercent(m.value) : formatMetric(m.value)}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>

            {synthetic_data_validation.status === 'available' && (
              <Card className="border-amber-200/50 bg-gradient-to-r from-amber-50/30 to-orange-50/30">
                <CardContent className="flex items-start gap-3 py-4">
                  <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-medium text-amber-800">Synthetic Data Advisory</p>
                    <p className="text-sm text-amber-700 mt-1">
                      {synthetic_data_validation.note}
                    </p>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* Fairness Tab */}
        <TabsContent value="fairness">
          <div className="grid gap-6 md:grid-cols-2 mt-4">
            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Protected Attributes Tested</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {fairness_analysis.protected_attributes.map((attr) => (
                    <Badge key={attr} variant="secondary" className="capitalize">
                      {attr.replace(/_/g, ' ')}
                    </Badge>
                  ))}
                </div>
                <p className="text-sm text-muted-foreground mt-4">
                  <span className="font-medium">Mitigation strategy:</span> {fairness_analysis.mitigation}
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Disparate Impact Ratios</CardTitle>
                <CardDescription>Values between 0.8 and 1.25 indicate fairness (80% rule)</CardDescription>
              </CardHeader>
              <CardContent className="px-0">
                {Object.keys(fairness_analysis.disparate_impact_ratio).length > 0 ? (
                  <div className="divide-y divide-border">
                    {Object.entries(fairness_analysis.disparate_impact_ratio).map(([attr, value]) => {
                      const ratio = typeof value === 'object' ? value.disparate_impact_ratio : value
                      const passes = typeof value === 'object' ? value.passes_80_percent_rule : (ratio != null && ratio >= 0.8 && ratio <= 1.25)
                      return (
                        <div key={attr} className="grid grid-cols-3 gap-4 px-6 py-2.5 items-center">
                          <span className="text-sm text-muted-foreground capitalize">{attr.replace(/_/g, ' ')}</span>
                          <span className="text-sm font-mono tabular-nums text-right">
                            {typeof ratio === 'number' ? ratio.toFixed(4) : '\u2014'}
                          </span>
                          <span className="text-right">
                            {passes != null && (
                              passes
                                ? <Badge variant="success">Pass</Badge>
                                : <Badge variant="destructive">Fail</Badge>
                            )}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <p className="px-6 text-sm text-muted-foreground">No disparate impact data available.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Governance Tab */}
        <TabsContent value="governance">
          <div className="grid gap-6 md:grid-cols-2 mt-4">
            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Decision Thresholds</CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <div className="divide-y divide-border">
                  <KeyValue label="Approve" value={governance.decision_thresholds.approve != null ? governance.decision_thresholds.approve.toFixed(2) : '\u2014'} mono />
                  <KeyValue label="Deny" value={governance.decision_thresholds.deny != null ? governance.decision_thresholds.deny.toFixed(2) : '\u2014'} mono />
                  <KeyValue label="Human Review" value={governance.decision_thresholds.human_review != null ? governance.decision_thresholds.human_review.toFixed(2) : '\u2014'} mono />
                  <KeyValue label="Explainability" value={governance.explainability_method || '\u2014'} />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Model Lifecycle</CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <div className="divide-y divide-border">
                  <KeyValue label="Status" value={
                    <Badge variant={governance.status === 'active' ? 'success' : 'destructive'}>
                      {governance.status === 'active' ? 'Active' : 'Retired'}
                    </Badge>
                  } />
                  <KeyValue label="Next Review" value={
                    governance.next_review_date ? (
                      <span className="inline-flex items-center gap-1.5">
                        <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                        {formatDate(governance.next_review_date)}
                      </span>
                    ) : '\u2014'
                  } />
                  {governance.retired_at && (
                    <KeyValue label="Retired At" value={formatDate(governance.retired_at)} />
                  )}
                </div>
              </CardContent>
            </Card>

            {Object.keys(governance.retraining_policy).length > 0 && (
              <Card>
                <CardHeader className="pb-4">
                  <CardTitle className="text-base">Retraining Policy</CardTitle>
                </CardHeader>
                <CardContent className="px-0">
                  <div className="divide-y divide-border">
                    {Object.entries(governance.retraining_policy).map(([key, value]) => (
                      <KeyValue
                        key={key}
                        label={key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                        value={typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      />
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Independent Validation</CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <div className="divide-y divide-border">
                  <KeyValue label="Status" value={
                    <Badge variant={independent_validation.status === 'validated' ? 'success' : 'warning'}>
                      {independent_validation.status === 'validated' ? 'Validated' : 'Not Validated'}
                    </Badge>
                  } />
                  {independent_validation.status === 'validated' ? (
                    <>
                      {independent_validation.outcome && <KeyValue label="Outcome" value={independent_validation.outcome} />}
                      {independent_validation.validator && <KeyValue label="Validator" value={independent_validation.validator} />}
                      {independent_validation.validation_date && <KeyValue label="Date" value={formatDate(independent_validation.validation_date)} />}
                      {independent_validation.methodology && <KeyValue label="Methodology" value={independent_validation.methodology} />}
                      {independent_validation.signed_off != null && (
                        <KeyValue label="Signed Off" value={
                          independent_validation.signed_off
                            ? <CheckCircle2 className="h-4 w-4 text-emerald-600 ml-auto" />
                            : <XCircle className="h-4 w-4 text-red-500 ml-auto" />
                        } />
                      )}
                      {independent_validation.next_validation_due && (
                        <KeyValue label="Next Validation" value={formatDate(independent_validation.next_validation_due)} />
                      )}
                    </>
                  ) : (
                    <div className="px-6 py-2.5">
                      <p className="text-sm text-muted-foreground">{independent_validation.note}</p>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Regulatory Compliance</CardTitle>
              </CardHeader>
              <CardContent className="px-0">
                <div className="divide-y divide-border">
                  {Object.entries(regulatory_compliance).map(([reg, compliant]) => {
                    const labels: Record<string, string> = {
                      apra_cpg_235: 'APRA CPG 235',
                      nccp_act: 'NCCP Act',
                      banking_code: 'Banking Code of Practice',
                    }
                    return (
                      <div key={reg} className="grid grid-cols-2 gap-4 px-6 py-2.5 items-center">
                        <span className="text-sm text-muted-foreground">{labels[reg] || reg}</span>
                        <span className="text-right">
                          {compliant ? (
                            <Badge variant="success">
                              <Shield className="h-3 w-3 mr-1" />
                              Compliant
                            </Badge>
                          ) : (
                            <Badge variant="destructive">Non-Compliant</Badge>
                          )}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Limitations Tab */}
        <TabsContent value="limitations">
          <div className="grid gap-6 md:grid-cols-2 mt-4">
            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Known Limitations</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-3">
                  {limitations.map((limitation, i) => (
                    <li key={i} className="flex items-start gap-3">
                      <AlertTriangle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                      <span className="text-sm">{limitation}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Out-of-Scope Uses</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{intended_use.out_of_scope}</p>
              </CardContent>
            </Card>

            <Card className="md:col-span-2">
              <CardHeader className="pb-4">
                <CardTitle className="text-base">Ethical Considerations</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-3">
                  <li className="flex items-start gap-3">
                    <Shield className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
                    <span className="text-sm">Fairness analysis is performed across protected attributes ({fairness_analysis.protected_attributes.join(', ')}) with {fairness_analysis.mitigation.toLowerCase()} applied.</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <Shield className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
                    <span className="text-sm">Model decisions use {governance.explainability_method || 'explainability methods'} for transparency and auditability.</span>
                  </li>
                  <li className="flex items-start gap-3">
                    <Shield className="h-4 w-4 text-blue-500 shrink-0 mt-0.5" />
                    <span className="text-sm">Human review is triggered for borderline decisions with confidence below the review threshold.</span>
                  </li>
                </ul>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
