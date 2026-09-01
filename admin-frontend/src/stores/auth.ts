import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiFetch } from '@/services/api'

export interface AuthUser {
  id: number
  username: string
  balance?: string
  is_staff?: boolean
  is_superuser?: boolean
}
interface MeResponse extends AuthUser {
  is_authenticated: true
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const checked = ref(false)
  const isLoggedIn = computed<boolean>(() => user.value !== null)
  const isAdmin = computed<boolean>(() => Boolean(user.value?.is_staff || user.value?.is_superuser))

  async function fetchMe(): Promise<boolean> {
    try {
      const me = await apiFetch<MeResponse>('/api/auth/me')
      user.value = {
        id: me.id,
        username: me.username,
        balance: me.balance,
        is_staff: me.is_staff,
        is_superuser: me.is_superuser,
      }
      return true
    } catch {
      user.value = null
      return false
    } finally {
      checked.value = true
    }
  }
  async function login(username: string, password: string): Promise<void> {
    const data = await apiFetch<AuthUser>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    user.value = {
      id: data.id,
      username: data.username,
      balance: data.balance,
      is_staff: data.is_staff,
      is_superuser: data.is_superuser,
    }
    checked.value = true
  }
  async function signup(username: string, password: string): Promise<void> {
    const data = await apiFetch<AuthUser>('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ username, password1: password, password2: password }),
    })
    user.value = {
      id: data.id,
      username: data.username,
      balance: data.balance,
      is_staff: data.is_staff,
      is_superuser: data.is_superuser,
    }
    checked.value = true
  }
  async function logout(): Promise<void> {
    user.value = null
    checked.value = true
    if (typeof localStorage !== 'undefined') localStorage.removeItem('token')
    try {
      await apiFetch<{ detail: string }>('/api/auth/logout', { method: 'POST' })
    } catch {}
  }
  void apiFetch<{ detail: string }>('/api/csrf').catch(() => {})
  return { user, checked, isLoggedIn, isAdmin, fetchMe, login, signup, logout }
})
