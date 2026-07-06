import client from './client'
import type { AdminUser, AdminDashboard } from '@/types'

export function getAdminDashboard() {
  return client.get<AdminDashboard>('/admin/dashboard')
}

export function getAdminUsers() {
  return client.get<{ items: AdminUser[]; total: number }>('/admin/users')
}

export function updateUserRole(id: number, role: 'admin' | 'user') {
  return client.put<AdminUser>(`/admin/users/${id}`, { role })
}

export function toggleUserActive(id: number, isActive: boolean) {
  return client.put<AdminUser>(`/admin/users/${id}`, { is_active: isActive })
}

export function deleteUser(id: number) {
  return client.delete(`/admin/users/${id}`)
}

export function updateUser(id: number, data: {
  username?: string
  email?: string | null
  role?: 'admin' | 'user'
  is_active?: boolean
  org_tags?: string | null
}) {
  return client.put<AdminUser>(`/admin/users/${id}`, data)
}
