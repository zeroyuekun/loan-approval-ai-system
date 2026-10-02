import type { Metadata } from 'next'
import { connection } from 'next/server'
import { Inter } from 'next/font/google'
import './globals.css'
import { Providers } from './providers'
import { Toaster } from 'sonner'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'AussieLoanAI - Loan Approval System',
  description: 'AI-powered loan approval and processing system',
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  // Render every page per request. The CSP nonce (src/proxy.ts) is only
  // applied to scripts during dynamic rendering; a page prerendered at build
  // time has no nonce and the browser would block its inline scripts.
  await connection()

  return (
    <html lang="en">
      <body className={inter.className}>
        <Providers>
          {children}
        </Providers>
        <Toaster richColors position="top-right" />
      </body>
    </html>
  )
}
