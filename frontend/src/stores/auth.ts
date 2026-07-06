import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { User, LoginRequest, RegisterRequest } from '@/types'
import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const isAuthenticated = ref(false)
  const isLoading = ref(false)

  async function login(data: LoginRequest) {
    isLoading.value = true
    try {
      const res = await authApi.login(data)
      const { access_token, refresh_token } = res.data
      localStorage.setItem('access_token', access_token)
      localStorage.setItem('refresh_token', refresh_token)
      await fetchUser()
      return true
    } finally {
      isLoading.value = false
    }
  }

  async function register(data: RegisterRequest) {
    isLoading.value = true
    try {
      await authApi.register(data)
      return true
    } finally {
      isLoading.value = false
    }
  }

  async function fetchUser() {
    const token = localStorage.getItem('access_token')
    if (!token) {
      user.value = null
      isAuthenticated.value = false
      return
    }
    try {
      const res = await authApi.getCurrentUser()
      user.value = res.data
      isAuthenticated.value = true
    } catch {
      user.value = null
      isAuthenticated.value = false
    }
  }

  async function logoutUser() {
    try {
      // Blacklist the access token server-side first
      await authApi.logout()
    } catch {
      // ignore network / server errors — logout proceeds client-side
    } finally {
      // Always clear local state, regardless of API success
      user.value = null
      isAuthenticated.value = false
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    }
  }

  function checkAuth() {
    const token = localStorage.getItem('access_token')
    if (token && user.value) {
      isAuthenticated.value = true
    } else if (!token) {
      isAuthenticated.value = false
      user.value = null
    }
  }

  return {
    user,
    isAuthenticated,
    isLoading,
    login,
    register,
    fetchUser,
    logoutUser,
    checkAuth,
  }
})
