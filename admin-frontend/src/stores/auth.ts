import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiFetch } from '@/services/api'

export interface AuthUser {
  id: number
  username: string
}
interface MeResponse extends AuthUser {
  is_authenticated: true
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const isLoggedIn = computed<boolean>(() => user.value !== null)

  async function fetchMe(): Promise<boolean> {
    try {
      const me = await apiFetch<MeResponse>('/api/auth/me')
      user.value = { id: me.id, username: me.username }
      return true
    } catch {
      user.value = null
      return false
    }
  }
  async function login(username: string, password: string): Promise<void> {
    const data = await apiFetch<AuthUser>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    user.value = data
  }
  async function signup(username: string, password: string): Promise<void> {
    const data = await apiFetch<AuthUser>('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ username, password1: password, password2: password }),
    })
    user.value = data
  }
  async function logout(): Promise<void> {
    user.value = null
    if (typeof localStorage !== 'undefined') localStorage.removeItem('token')
    try {
      await apiFetch<{ detail: string }>('/api/auth/logout', { method: 'POST' })
    } catch {}
  }
  void apiFetch<{ detail: string }>('/api/csrf').catch(() => {})
  return { user, isLoggedIn, fetchMe, login, signup, logout }
})
