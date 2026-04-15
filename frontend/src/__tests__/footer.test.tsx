import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { Footer } from '@/components/layout/Footer';
import { expectNoAxeViolations } from '@/test/axe-helper';

describe('<Footer />', () => {
  const originalEnv = process.env.NEXT_PUBLIC_ACL_NUMBER;

  beforeEach(() => {
    process.env.NEXT_PUBLIC_ACL_NUMBER = '123456';
  });

  afterEach(() => {
    process.env.NEXT_PUBLIC_ACL_NUMBER = originalEnv;
  });

  it('renders as a landmark with contentinfo role', () => {
    render(<Footer />);
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('shows the ACL number from env', () => {
    render(<Footer />);
    expect(screen.getByText(/ACL\s*123456/)).toBeInTheDocument();
  });

  it('falls back to the demo ACL number when env is unset', () => {
    delete process.env.NEXT_PUBLIC_ACL_NUMBER;
    render(<Footer />);
    expect(screen.getByText(/DEMO-LENDER-000000/)).toBeInTheDocument();
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
