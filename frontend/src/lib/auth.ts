'use client'
import { createContext, useContext } from 'react'
import { User } from '@/types'
import type { RegisterPayload } from '@/lib/api'

/**
 * Outcome of a login attempt that did not throw. `otp_required` means the
 * password was accepted but the account has a TOTP device: call login again
 * with the 6-digit code. Bad credentials and bad codes reject (HTTP 400).
 */
export type LoginResult = { status: 'ok' } | { status: 'otp_required'; detail?: string }

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string, otpToken?: string) => Promise<LoginResult>;
  register: (data: RegisterPayload) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  login: async () => ({ status: 'ok' }),
  register: async () => {},
  logout: () => {},
})

export const useAuth = () => useContext(AuthContext)
