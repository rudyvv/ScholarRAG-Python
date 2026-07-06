import client from './client'
import type { User, LoginRequest, RegisterRequest, AuthTokens } from '@/types'

export function login(data: LoginRequest) {
  return client.post<AuthTokens>('/auth/login', data)
}

export function register(data: RegisterRequest) {
  return client.post<User>('/auth/register', data)
}

export function refreshToken(refreshToken: string) {
  return client.post<AuthTokens>('/auth/refresh', { refresh_token: refreshToken })
}

export function getCurrentUser() {
  return client.get<User>('/auth/me')
}

export function logout() {
  return client.post('/auth/logout')
}
