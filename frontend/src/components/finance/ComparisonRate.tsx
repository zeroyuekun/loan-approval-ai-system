import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

export interface ComparisonRateProps {
  headlineRate: number;
  comparisonRate: number | null;
  loanAmount: number;
  termYears: number;
}

const percentFormatter = new Intl.NumberFormat('en-AU', {
  style: 'percent',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const NCCP_DISCLAIMER =
  'WARNING: This comparison rate applies only to the example given and may not include all fees and charges. Different terms, fees or other loan amounts might result in a different comparison rate.';

const DEMO_DISCLAIMER =
  'Illustrative only - this demo does not include lender fees. Production comparison rate will reflect the standardised NCCP Sch 1 calculation.';

export function ComparisonRate({
  headlineRate,
  comparisonRate,
  loanAmount,
  termYears,
}: ComparisonRateProps) {
  const effectiveComparison = comparisonRate ?? headlineRate;
  const hasReal = comparisonRate !== null;

  return (
    <TooltipProvider>
      <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="font-medium text-muted-foreground">Headline</dt>
        <dd>{percentFormatter.format(headlineRate)} p.a.</dd>

        <dt className="font-medium text-muted-foreground">
          Comparison rate
          <Tooltip>
            <TooltipTrigger
              aria-label="Comparison rate disclaimer"
              className="ml-1 align-super text-xs"
            >
              *
            </TooltipTrigger>
            <TooltipContent className="max-w-sm">
              <p>{NCCP_DISCLAIMER}</p>
              {!hasReal ? <p className="mt-2">{DEMO_DISCLAIMER}</p> : null}
            </TooltipContent>
          </Tooltip>
        </dt>
        <dd>
          {percentFormatter.format(effectiveComparison)} p.a.
          {!hasReal ? (
            <span className="ml-2 text-xs italic text-muted-foreground">
              Illustrative only
            </span>
          ) : null}
        </dd>

        <dt className="sr-only">Example loan amount</dt>
        <dd className="col-span-2 mt-1 text-xs text-muted-foreground">
          Example based on a {percentFormatter.format(headlineRate)} loan of $
          {loanAmount.toLocaleString('en-AU')} over {termYears} years.
        </dd>
      </dl>
    </TooltipProvider>
  );
}
