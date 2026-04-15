import Link from 'next/link';

const LAST_UPDATED_DATE = '2026-04-15';
const FALLBACK_ACL = 'DEMO-LENDER-000000';
const LENDER_NAME = 'Demo Lender Pty Ltd';

export function Footer() {
  const acl = process.env.NEXT_PUBLIC_ACL_NUMBER ?? FALLBACK_ACL;

  return (
    <footer
      role="contentinfo"
      className="border-t border-border bg-muted/30 text-xs text-muted-foreground"
    >
      <div className="mx-auto max-w-6xl space-y-2 px-6 py-6">
        <p>
          <strong className="text-foreground">{LENDER_NAME}</strong>
          &nbsp;·&nbsp;ACL <span aria-label="Australian Credit Licence number">{acl}</span>
        </p>
        <nav aria-label="Legal and regulatory links">
          <ul className="flex flex-wrap gap-x-4 gap-y-1">
            <li>
              <Link href="/rights#credit-guide" className="hover:underline">
                Credit Guide
              </Link>
            </li>
            <li>
              <Link href="/rights#privacy" className="hover:underline">
                Privacy
              </Link>
            </li>
            <li>
              <Link href="/rights" className="hover:underline">
                Terms &amp; Rights
              </Link>
            </li>
          </ul>
        </nav>
        <p>
          <span aria-label="Australian Financial Complaints Authority">AFCA</span>:{' '}
          <a href="tel:1800931678" className="hover:underline">
            1800 931 678
          </a>{' '}
          &middot;{' '}
          <a
            href="https://www.afca.org.au"
            className="hover:underline"
            target="_blank"
            rel="noopener noreferrer"
          >
            www.afca.org.au
          </a>
        </p>
        <p>{LENDER_NAME} is not an Authorised Deposit-taking Institution.</p>
        <p className="text-[10px] opacity-70">Last updated: {LAST_UPDATED_DATE}</p>
      </div>
    </footer>
  );
}
