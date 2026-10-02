'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'
import { authApi } from '@/lib/api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'

function errorDetail(err: unknown, fallback: string): string {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
}

/** The base32 secret from an otpauth:// URI, for typing into an app by hand. */
function secretFrom(uri: string): string | null {
  const match = uri.match(/[?&]secret=([^&]+)/i)
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * TOTP enrolment for staff. Login sends officers and admins here when the
 * backend flags `requires_2fa_setup`, and the API client does on any
 * `2fa_enrolment_required` refusal; once confirmed, every later login asks
 * for a code from the authenticator app.
 */
export default function TwoFactorSetupPage() {
  const [code, setCode] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const queryClient = useQueryClient()

  const status = useQuery({
    queryKey: ['twoFactorStatus'],
    queryFn: async () => (await authApi.twoFactorStatus()).data,
  })
  const setup = useMutation({
    mutationFn: async () => (await authApi.twoFactorSetup()).data,
  })
  const verify = useMutation({
    mutationFn: async (token: string) => (await authApi.twoFactorVerify(token)).data,
    onSuccess: () => {
      setConfirmed(true)
      // Keep the cached status in step: coming back to this page must show
      // "on", not offer a setup the backend would refuse.
      queryClient.setQueryData(['twoFactorStatus'], (old: { enabled: boolean; required: boolean } | undefined) =>
        old ? { ...old, enabled: true } : { enabled: true, required: true },
      )
    },
  })

  const enabled = confirmed || status.data?.enabled
  const secret = setup.data ? secretFrom(setup.data.provisioning_uri) : null

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Two-factor authentication</h1>
        <p className="text-muted-foreground">
          Staff accounts sign in with a password and a code from an authenticator app.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
            Authenticator app
          </CardTitle>
          <CardDescription>
            Use any TOTP app, such as Google Authenticator, Microsoft Authenticator or 1Password.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {status.isLoading ? (
            <Skeleton className="h-24 w-full" />
          ) : enabled ? (
            <div className="space-y-3">
              <p className="text-sm font-medium text-green-700">
                Two-factor authentication is on. You will be asked for a code each time you sign in.
              </p>
              <Button asChild>
                <Link href="/dashboard">Go to dashboard</Link>
              </Button>
            </div>
          ) : !setup.data ? (
            <div className="space-y-3">
              {status.isError && (
                <p className="text-sm text-red-600">Could not check your two-factor status.</p>
              )}
              {setup.isError && (
                <p className="text-sm text-red-600">
                  {errorDetail(setup.error, 'Could not start setup. Please try again.')}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={() => setup.mutate()} disabled={setup.isPending}>
                  {setup.isPending ? 'Starting...' : 'Set up authenticator'}
                </Button>
              </div>
            </div>
          ) : (
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault()
                verify.mutate(code)
              }}
            >
              <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
                <li>Scan the QR code with your authenticator app, or enter the key by hand.</li>
                <li>Type the 6-digit code the app shows.</li>
              </ol>
              {setup.data.qr_code_base64 && (
                // eslint-disable-next-line @next/next/no-img-element -- inline data URI, nothing to optimise
                <img
                  src={`data:image/png;base64,${setup.data.qr_code_base64}`}
                  alt="QR code for your authenticator app"
                  className="h-48 w-48 rounded border"
                />
              )}
              {secret && (
                <p className="text-sm">
                  Setup key: <code className="break-all rounded bg-muted px-1 py-0.5 font-mono">{secret}</code>
                </p>
              )}
              <div className="space-y-2">
                <Label htmlFor="totp-code">6-digit code</Label>
                <Input
                  id="totp-code"
                  inputMode="numeric"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                  required
                />
              </div>
              {verify.isError && (
                <p className="text-sm text-red-600">
                  {errorDetail(verify.error, 'That code did not work. Please try again.')}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" disabled={code.length !== 6 || verify.isPending}>
                  {verify.isPending ? 'Confirming...' : 'Confirm'}
                </Button>
              </div>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
