import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Scale, Shield, HelpCircle, FileText, Phone, AlertCircle, Building2 } from 'lucide-react'

export default function ConsumerRightsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-12">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Your Rights</h1>
        <p className="text-muted-foreground mt-2">
          Understanding how we assess your application and your rights as a borrower.
        </p>
      </div>

      {/* How Decisions Are Made */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Scale className="h-5 w-5 text-blue-600" />
            How We Assess Your Application
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed">
          <p>
            Your loan application is assessed using an AI-assisted credit decision model
            combined with human oversight. The model evaluates factors including your income,
            employment, credit history, existing debts, and expenses to determine whether
            the loan is suitable for your financial situation.
          </p>
          <p>
            Every decision is explainable. If your application is not approved, you will
            receive specific reasons based on the factors that most influenced the outcome.
            These reasons are drawn from standardised codes mapped to individual assessment
            criteria, not generic categories.
          </p>
          <p>
            Applications with certain characteristics — such as potential bias concerns
            or low-confidence predictions — are automatically escalated for human review
            by a qualified lending officer.
          </p>
        </CardContent>
      </Card>

      {/* Responsible Lending */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-green-600" />
            Responsible Lending Obligations
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed">
          <p>
            Under Australian responsible lending laws, we are required to assess that
            any loan we offer is <strong>not unsuitable</strong> for you. This means we must
            take reasonable steps to:
          </p>
          <ul className="list-disc pl-6 space-y-1">
            <li>Make reasonable inquiries about your financial situation</li>
            <li>Make reasonable inquiries about your requirements and objectives</li>
            <li>Take reasonable steps to verify your financial situation</li>
            <li>Assess whether the credit contract is not unsuitable for you</li>
          </ul>
          <p>
            We stress-test your repayment capacity at a rate buffer above the product
            rate to ensure you can meet obligations even if interest rates rise.
          </p>
        </CardContent>
      </Card>

      {/* Credit Reporting Rights */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5 text-indigo-600" />
            Your Credit Reporting Rights
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed">
          <p>
            If your application is declined, you have the right to:
          </p>
          <ul className="list-disc pl-6 space-y-1">
            <li>
              <strong>Request your credit score</strong> — the credit score used in assessing
              your application is disclosed in your decision notification.
            </li>
            <li>
              <strong>Obtain a free credit report</strong> — you are entitled to a free copy of
              your credit report from Equifax or Illion within 90 days of a credit decision.
            </li>
            <li>
              <strong>Correct inaccurate information</strong> — if your credit report contains
              errors, you can request corrections directly with the credit reporting body.
            </li>
            <li>
              <strong>Understand the reasons</strong> — you will receive specific factors that
              contributed to the decision, not generic explanations.
            </li>
          </ul>
        </CardContent>
      </Card>

      {/* Hardship Assistance */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <HelpCircle className="h-5 w-5 text-amber-600" />
            Financial Hardship Assistance
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed">
          <p>
            If you are experiencing financial difficulty and are unable to meet your
            loan repayments, you may be entitled to hardship assistance. Options may
            include:
          </p>
          <ul className="list-disc pl-6 space-y-1">
            <li>Temporary reduction in repayment amounts</li>
            <li>Extension of the loan term</li>
            <li>Temporary deferral of repayments</li>
            <li>Other arrangements based on your circumstances</li>
          </ul>
          <p>
            Contact us as early as possible if you anticipate difficulty making repayments.
            Early contact gives us the best opportunity to assist you.
          </p>
        </CardContent>
      </Card>

      {/* Privacy */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-red-600" />
            Privacy and Data Protection
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed">
          <p>
            Your personal information is protected under the Privacy Act 1988 (Cth) and
            the Australian Privacy Principles. We collect, use, and disclose your
            personal information only for the purpose of assessing and managing your
            loan application.
          </p>
          <ul className="list-disc pl-6 space-y-1">
            <li>Sensitive personal data is encrypted at rest using AES encryption</li>
            <li>Access to your data is restricted to authorised personnel only</li>
            <li>Records are retained for 7 years as required by the AML/CTF Act 2006</li>
            <li>You can request access to, or correction of, your personal information at any time</li>
          </ul>
        </CardContent>
      </Card>

      {/* Complaints */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-5 w-5 text-slate-600" />
            Making a Complaint
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed">
          <p>
            If you are not satisfied with a lending decision or any aspect of our
            service, you can:
          </p>
          <ol className="list-decimal pl-6 space-y-2">
            <li>
              <strong>Contact us directly</strong> — our internal dispute resolution
              team will review your complaint and respond within 30 days.
            </li>
            <li>
              <strong>Lodge a complaint with AFCA</strong> — if your complaint is not
              resolved to your satisfaction, you can refer it to the Australian Financial
              Complaints Authority (AFCA), an independent external dispute resolution scheme.
            </li>
          </ol>
          <div className="mt-4 rounded-lg bg-muted p-4">
            <p className="font-medium text-sm">Australian Financial Complaints Authority</p>
            <div className="mt-2 space-y-1 text-sm text-muted-foreground">
              <p className="flex items-center gap-2">
                <Phone className="h-3.5 w-3.5" />
                1800 931 678 (free call)
              </p>
              <p>Website: www.afca.org.au</p>
              <p>Email: info@afca.org.au</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
