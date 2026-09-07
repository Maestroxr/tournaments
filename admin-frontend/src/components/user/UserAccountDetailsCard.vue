<script setup lang="ts">
import AppInput from '@/components/AppInput.vue'
import { useI18n } from '@/i18n'

withDefaults(defineProps<{
  errors?: Record<string, string>
}>(), {
  errors: () => ({}),
})

const username = defineModel<string>('username', { required: true })
const phoneNumber = defineModel<string>('phoneNumber', { required: true })
const emit = defineEmits<{ changed: [field: 'username' | 'phone_number'] }>()
const { t } = useI18n()
</script>

<template>
  <section class="rounded-xl border border-zinc-200 bg-white p-5 sm:p-6">
    <div class="mb-5 flex items-center gap-3">
      <span class="grid h-9 w-9 place-items-center rounded-lg bg-sky-400/15 text-sky-200">
        <i class="bi bi-person-vcard" />
      </span>
      <div>
        <h2 class="text-lg font-semibold text-black">{{ t('users.accountDetails') }}</h2>
        <p class="text-xs text-zinc-500">{{ t('users.accountDetailsHint') }}</p>
      </div>
    </div>
    <div class="grid gap-4 sm:grid-cols-2">
      <AppInput
        v-model="username"
        :label="t('users.username')"
        :placeholder="t('users.usernamePlaceholder')"
        :error="errors.username"
        autocomplete="username"
        @update:model-value="emit('changed', 'username')"
      />
      <AppInput
        v-model="phoneNumber"
        :label="t('users.phoneOptional')"
        :placeholder="t('users.phonePlaceholder')"
        type="tel"
        :error="errors.phone_number"
        autocomplete="tel"
        @update:model-value="emit('changed', 'phone_number')"
      />
    </div>
  </section>
</template>
