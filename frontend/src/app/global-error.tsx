'use client'

import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: '#0f172a',
          color: '#e2e8f0',
          fontFamily:
            'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        }}
      >
        <div
          style={{
            maxWidth: '28rem',
            width: '100%',
            textAlign: 'center',
            padding: '2.5rem',
            borderRadius: '1rem',
            backgroundColor: '#1e293b',
            border: '1px solid #334155',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
          }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="48"
            height="48"
            viewBox="0 0 24 24"
            fill="none"
            stroke="#f87171"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ margin: '0 auto 1.5rem' }}
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <h2
            style={{
              fontSize: '1.25rem',
              fontWeight: 600,
              margin: '0 0 0.75rem',
              color: '#f1f5f9',
            }}
          >
            Something went wrong
          </h2>
          <p
            style={{
              fontSize: '0.875rem',
              color: '#94a3b8',
              margin: '0 0 1.5rem',
              lineHeight: 1.5,
            }}
          >
            An unexpected error occurred. Please try again or return to the home page.
          </p>
          <div
            style={{
              display: 'flex',
              gap: '0.75rem',
              justifyContent: 'center',
            }}
          >
            <button
              onClick={reset}
              style={{
                padding: '0.625rem 1.25rem',
                borderRadius: '0.5rem',
                border: 'none',
                backgroundColor: '#3b82f6',
                color: '#fff',
                fontSize: '0.875rem',
                fontWeight: 500,
                cursor: 'pointer',
              }}
            >
              Try Again
            </button>
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages -- global-error renders outside root layout, Link/router unavailable */}
            <a
              href="/"
              style={{
                padding: '0.625rem 1.25rem',
                borderRadius: '0.5rem',
                border: '1px solid #475569',
                backgroundColor: 'transparent',
                color: '#cbd5e1',
                fontSize: '0.875rem',
                fontWeight: 500,
                textDecoration: 'none',
                display: 'inline-flex',
                alignItems: 'center',
              }}
            >
              Go Home
            </a>
          </div>
        </div>
      </body>
    </html>
  )
}
