import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import userEvent from '@testing-library/user-event';
import { ComparisonRate } from '@/components/finance/ComparisonRate';
import { expectNoAxeViolations } from '@/test/axe-helper';

describe('<ComparisonRate />', () => {
  it('formats rates using en-AU locale', () => {
    render(
      <ComparisonRate
        headlineRate={0.0625}
        comparisonRate={0.0642}
        loanAmount={150000}
        termYears={25}
      />,
    );
    expect(screen.getByText('6.25% p.a.')).toBeInTheDocument();
    expect(screen.getByText('6.42% p.a.')).toBeInTheDocument();
  });

  it('renders the headline rate into the comparison slot with a note when comparison is missing', () => {
    render(
      <ComparisonRate
        headlineRate={0.0625}
        comparisonRate={null}
        loanAmount={150000}
        termYears={25}
      />,
    );
    expect(screen.getAllByText('6.25% p.a.').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Illustrative only/i)).toBeInTheDocument();
  });

  it('exposes NCCP Sch 1 disclaimer on the comparison-rate asterisk', async () => {
    const user = userEvent.setup();
    render(
      <ComparisonRate
        headlineRate={0.0625}
        comparisonRate={0.0642}
        loanAmount={150000}
        termYears={25}
      />,
    );
    await user.hover(screen.getByText('*'));
    // Radix Tooltip renders the content in a popper and a visually-hidden
    // a11y mirror, so findAllByText is the stable assertion here.
    const matches = await screen.findAllByText(
      /WARNING: This comparison rate applies only to/i,
    );
    expect(matches.length).toBeGreaterThan(0);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ComparisonRate
        headlineRate={0.0625}
        comparisonRate={0.0642}
        loanAmount={150000}
        termYears={25}
      />,
    );
    await expectNoAxeViolations(container);
  });
});
