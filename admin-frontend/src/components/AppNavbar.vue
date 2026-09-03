<script setup lang="ts">
import { RouterLink, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Button from 'primevue/button'
import AppTabs from '@/components/AppTabs.vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import { useI18n } from '@/i18n'

const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()

async function handleLogout() {
  await auth.logout()
  router.push('/login')
}
</script>

<template>
  <header class="admin-topbar">
    <div class="admin-topbar-inner">
      <RouterLink to="/dashboard" class="admin-brand" :aria-label="t('nav.brand')">
        <span class="admin-brand-mark" aria-hidden="true">B</span>
        <span>{{ t('nav.brand') }}</span>
      </RouterLink>
      <AppTabs v-if="auth.isLoggedIn" />

      <div class="admin-account">
        <template v-if="auth.isLoggedIn">
          <div class="admin-account-meta">
            <span class="admin-account-name"><i class="bi bi-person" aria-hidden="true"></i> {{ auth.user?.username }}</span>
            <span class="admin-balance">{{ Number(auth.user?.balance || 0).toFixed(2) }}</span>
          </div>
          <LanguageSwitcher />
          <Button :label="t('common.logout')" icon="bi bi-box-arrow-right" size="small" text @click="handleLogout" />
        </template>
        <template v-else>
          <LanguageSwitcher />
          <Button as="router-link" to="/login" :label="t('common.login')" icon="bi bi-door-open" size="small" severity="secondary" />
        </template>
      </div>
    </div>
  </header>
</template>
