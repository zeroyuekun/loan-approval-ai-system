import Link from 'next/link'

export function ComplianceFooter() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t bg-muted/50 mt-auto">
      <div className="mx-auto max-w-4xl px-4 py-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">
              AussieLoanAI Pty Ltd
            </p>
            <p className="text-xs text-muted-foreground/80">
              Australian Credit Licence No. 012345
            </p>
            <p className="text-xs text-muted-foreground/80">
              ABN 00 000 000 000
            </p>
          </div>

          <div className="space-y-1.5 text-xs text-muted-foreground/80">
            <p>
              Member of the{' '}
              <a
                href="https://www.afca.org.au"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-muted-foreground transition-colors"
              >
                Australian Financial Complaints Authority
              </a>{' '}
              (AFCA)
            </p>
            <p>
              <Link
                href="/rights"
                className="underline underline-offset-2 hover:text-muted-foreground transition-colors"
              >
                Privacy Policy
              </Link>
            </p>
          </div>
        </div>

        <p className="mt-4 text-[11px] text-muted-foreground/60">
          &copy; {currentYear} AussieLoanAI Pty Ltd. All rights reserved.
        </p>
      </div>
    </footer>
  )
}
