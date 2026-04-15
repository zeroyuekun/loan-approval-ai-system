import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { Footer } from '@/components/layout/Footer';
import { expectNoAxeViolations } from '@/test/axe-helper';

describe('<Footer />', () => {
  const originalAcl = process.env.NEXT_PUBLIC_ACL_NUMBER;
  const originalAbn = process.env.NEXT_PUBLIC_ABN;

  beforeEach(() => {
    process.env.NEXT_PUBLIC_ACL_NUMBER = '123456';
    process.env.NEXT_PUBLIC_ABN = '12 345 678 901';
  });

  afterEach(() => {
    process.env.NEXT_PUBLIC_ACL_NUMBER = originalAcl;
    process.env.NEXT_PUBLIC_ABN = originalAbn;
  });

  it('renders as a landmark with contentinfo role', () => {
    render(<Footer />);
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('shows the ACL number from env', () => {
    render(<Footer />);
    // ACL label and number live in sibling text + span nodes, so we
    // match on the combined textContent of the paragraph that holds them.
    const matcher = (_: string, el: Element | null) =>
      !!el && /ACL\s*123456/.test(el.textContent ?? '');
    expect(screen.getAllByText(matcher).length).toBeGreaterThan(0);
  });

  it('falls back to the demo ACL number when env is unset', () => {
    delete process.env.NEXT_PUBLIC_ACL_NUMBER;
    render(<Footer />);
    expect(screen.getByText(/DEMO-LENDER-000000/)).toBeInTheDocument();
  });

  it('shows the ABN from env', () => {
    render(<Footer />);
    const matcher = (_: string, el: Element | null) =>
      !!el && /ABN\s*12\s345\s678\s901/.test(el.textContent ?? '');
    expect(screen.getAllByText(matcher).length).toBeGreaterThan(0);
  });

  it('falls back to the demo ABN when env is unset', () => {
    delete process.env.NEXT_PUBLIC_ABN;
    render(<Footer />);
    const matcher = (_: string, el: Element | null) =>
      !!el && /ABN\s*00\s000\s000\s000/.test(el.textContent ?? '');
    expect(screen.getAllByText(matcher).length).toBeGreaterThan(0);
  });

  it('links to /rights for the credit guide', () => {
    render(<Footer />);
    const link = screen.getByRole('link', { name: /credit guide/i });
    expect(link).toHaveAttribute('href', '/rights#credit-guide');
  });

  it('shows the AFCA contact', () => {
    render(<Footer />);
    expect(screen.getByText(/1800 931 678/)).toBeInTheDocument();
  });

  it('includes the ADI disclaimer', () => {
    render(<Footer />);
    expect(
      screen.getByText(/is not an Authorised Deposit-taking Institution/i),
    ).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(<Footer />);
    await expectNoAxeViolations(container);
  });
});
