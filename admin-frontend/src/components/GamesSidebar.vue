<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from '@/i18n'
import type { GamesSection, SettingsSection } from '@/types/gameSettings'
defineProps<{ active: GamesSection; dirty: Record<SettingsSection, boolean> }>()
const { t } = useI18n()
const sections: GamesSection[] = [
  'monitor',
  'match',
  'friend',
  'money',
  'practice',
  'tournaments',
  'settings',
]
</script>
<template>
  <nav
    :aria-label="t('directPlay.navigation.title')"
    class="min-w-0 rounded-xl border border-white/15 bg-neutral-950 p-3 lg:sticky lg:top-5 lg:self-start"
  >
    <ul class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-1">
      <li v-for="section in sections" :key="section">
        <RouterLink
          :to="{ name: 'direct-play', query: { section } }"
          :aria-current="active === section ? 'page' : undefined"
          class="flex min-h-11 items-center justify-between gap-2 rounded-lg border border-transparent px-3 py-2 text-sm text-neutral-300 hover:bg-white/5 focus-visible:outline-2 focus-visible:outline-[#dfbc7c] aria-[current=page]:border-[#dfbc7c]/50 aria-[current=page]:bg-[#dfbc7c]/10 aria-[current=page]:text-[#dfbc7c]"
        >
          <span>{{ t('gameSettings.sections.' + section) }}</span
          ><span
            v-if="section !== 'monitor' && dirty[section]"
            :aria-label="t('gameSettings.unsaved')"
            class="size-2 shrink-0 rounded-full bg-[#dfbc7c]"
          ></span>
        </RouterLink>
      </li>
    </ul>
    <details :open="active === 'legacy'" class="mt-3 border-t border-white/15 pt-2">
      <summary
        class="min-h-11 cursor-pointer px-3 py-2 text-sm text-neutral-400 focus-visible:outline-2 focus-visible:outline-[#dfbc7c]"
      >
        {{ t('gameSettings.advanced') }}
      </summary>
      <RouterLink
        :to="{ name: 'direct-play', query: { section: 'legacy' } }"
        :aria-current="active === 'legacy' ? 'page' : undefined"
        class="flex min-h-11 items-center gap-2 rounded-lg px-3 py-2 text-sm text-neutral-400 focus-visible:outline-2 focus-visible:outline-[#dfbc7c] aria-[current=page]:text-[#dfbc7c]"
      >
        {{ t('gameSettings.sections.legacy')
        }}<span
          v-if="dirty.legacy"
          :aria-label="t('gameSettings.unsaved')"
          class="size-2 rounded-full bg-[#dfbc7c]"
        ></span>
      </RouterLink>
    </details>
  </nav>
</template>
