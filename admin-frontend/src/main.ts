import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import Aura from '@primevue/themes/aura'
import router from './router'
import './style.css'
import App from './App.vue'
import { useI18n } from './i18n'
import { primeVueLocales } from './i18n/primeVue'

const app = createApp(App)
const { locale } = useI18n()
app.use(createPinia())
app.use(PrimeVue, {
  theme: {
    preset: Aura,
  },
})
watch(
  locale,
  (value) => {
    const configuredLocale = app.config.globalProperties.$primevue.config.locale
    if (configuredLocale) Object.assign(configuredLocale, primeVueLocales[value])
  },
  { immediate: true },
)
app.use(ToastService)
app.use(router)
app.mount('#app')
