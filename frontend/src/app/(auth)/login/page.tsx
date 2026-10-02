'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function errorDetail(err: unknown, fallback: string): string {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback
}

export default function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  // Second step for accounts with an authenticator app (backend: requires_2fa)
  const [needsCode, setNeedsCode] = useState(false)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      const result = needsCode ? await login(username, password, code.trim()) : await login(username, password)
      if (result?.status === 'otp_required') {
        setNeedsCode(true)
        setCode('')
      }
    } catch (err: unknown) {
      setError(
        needsCode
          ? errorDetail(err, 'That code did not work. Please try again.')
          : errorDetail(err, 'Invalid credentials. Please try again.'),
      )
    } finally {
      setIsLoading(false)
    }
  }

  const startOver = () => {
    setNeedsCode(false)
    setCode('')
    setPassword('')
    setError('')
  }

  return (
    <div className="flex w-full flex-col items-center">
      <div className="w-full max-w-sm flex-1">
        <div className="space-y-2 mb-8">
          <h1 className="text-2xl font-bold tracking-tight">
            {needsCode ? 'Two-factor authentication' : 'Welcome back'}
          </h1>
          <p className="text-muted-foreground">
            {needsCode
              ? 'Enter the 6-digit code from your authenticator app'
              : 'Sign in to your account to continue'}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="rounded-lg bg-destructive/10 border border-destructive/20 p-3">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}
          {needsCode ? (
            <div className="space-y-2">
              <Label htmlFor="otp">Authentication code</Label>
              <Input
                id="otp"
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                required
                autoFocus
                autoComplete="one-time-code"
                placeholder="123456"
              />
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoComplete="username"
                  placeholder="Enter your username"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  placeholder="Enter your password"
                />
              </div>
            </>
          )}
          <Button type="submit" className="w-full" disabled={isLoading}>
            {needsCode
              ? (isLoading ? 'Verifying...' : 'Verify')
              : (isLoading ? 'Signing in...' : 'Sign In')}
          </Button>
          {needsCode && (
            <Button type="button" variant="ghost" className="w-full" onClick={startOver} disabled={isLoading}>
              Use a different account
            </Button>
          )}
        </form>

        <p className="text-sm text-muted-foreground text-center mt-6">
          Don&apos;t have an account?{' '}
          <Link href="/register" className="text-primary font-medium hover:underline">
            Create one
          </Link>
        </p>
      </div>
    </div>
  )
}
