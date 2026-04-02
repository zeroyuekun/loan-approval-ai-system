'use client'
import { createContext, useContext } from 'react'
import { User } from '@/types'
import type { RegisterPayload } from '@/lib/api'

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (data: RegisterPayload) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  login: async () => {},
  register: async () => {},
  logout: () => {},
})

export const useAuth = () => useContext(AuthContext)
