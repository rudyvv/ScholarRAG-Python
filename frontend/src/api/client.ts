import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'
import type { ApiError } from '@/types'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  // No default Content-Type — axios auto-detects: JSON → application/json, FormData → multipart/form-data
  // Backend wraps all responses in ApiResponse: {status, code, message, data: T}
  // Auto-unwrap so res.data returns T directly
  transformResponse: [
    (raw: string) => {
      try {
        const parsed = JSON.parse(raw)
        if (
          parsed &&
          typeof parsed === 'object' &&
          'status' in parsed &&
          'code' in parsed &&
          'message' in parsed
        ) {
          if (parsed.status === 'success' && 'data' in parsed) {
            return parsed.data
          }
          // Error responses: unwrap the message into a detail field
          // so existing catch(err => err.response?.data?.detail) works
          return { detail: parsed.message, ...parsed }
        }
        return parsed
      } catch {
        return raw
      }
    },
    // Second pass: convert FastAPI array-format detail to string
    (data: unknown) => {
      if (data && typeof data === 'object' && 'detail' in (data as Record<string, unknown>)) {
        const d = (data as Record<string, unknown>).detail
        if (Array.isArray(d)) {
          (data as Record<string, unknown>).detail = d.map((e: { msg?: string }) => e.msg ?? String(e)).join('; ')
        }
      }
      return data
    },
  ],
})

// Track refresh state to avoid multiple simultaneous refresh attempts
let isRefreshing = false
let failedQueue: Array<{
  resolve: (token: string) => void
  reject: (err: unknown) => void
}> = []

function processQueue(error: unknown, token: string | null = null) {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token!)
    }
  })
  failedQueue = []
}

// Request interceptor: attach access token
client.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('access_token')
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// Response interceptor: handle 401 with token refresh
client.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiError>) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise<string>((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return client(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      const refreshToken = localStorage.getItem('refresh_token')
      if (!refreshToken) {
        // No refresh token — caller (e.g. fetchUser) handles this gracefully
        return Promise.reject(error)
      }

      try {
        const response = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
        // Bare axios.post doesn't use transformResponse → access .data.data
        const { access_token, refresh_token: newRefreshToken } = response.data.data

        localStorage.setItem('access_token', access_token)
        localStorage.setItem('refresh_token', newRefreshToken)

        processQueue(null, access_token)

        originalRequest.headers.Authorization = `Bearer ${access_token}`
        return client(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        // No hard redirect — router.beforeEach + authStore.fetchUser() handles it
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  },
)

export default client
