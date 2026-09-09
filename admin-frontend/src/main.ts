import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import Aura from '@primevue/themes/aura'
import { definePreset } from '@primevue/themes'
import router from './router'
import './style.css'
import App from './App.vue'
import { useI18n } from './i18n'
import { primeVueLocales } from './i18n/primeVue'

const AdminPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '#edf3ff',
      100: '#dce8ff',
      200: '#c4d8ff',
      300: '#9fc1ff',
      400: '#729aff',
      500: '#3f79e4',
      600: '#2e64c7',
      700: '#244f9e',
      800: '#1d407e',
      900: '#172f60',
      950: '#0e1f42',
    },
    colorScheme: {
      dark: {
        surface: {
          0: '#f3f6ff',
          50: '#edf2ff',
          100: '#eaf0ff',
          200: '#d2dcf0',
          300: '#aab8d4',
          400: '#7e8daa',
          500: '#65718a',
          600: '#31425f',
          700: '#263653',
          800: '#1a2744',
          900: '#111a30',
          950: '#09101f',
        },
      },
    },
  },
  components: {
    select: {
      colorScheme: {
        dark: {
          option: {
            focusBackground: '#1a2744',
            selectedBackground: '#203a69',
            selectedFocusBackground: '#284a83',
            color: '#edf2ff',
            focusColor: '#f3f6ff',
            selectedColor: '#f3f6ff',
            selectedFocusColor: '#ffffff',
          },
        },
      },
    },
  },
})

const app = createApp(App)
const { locale } = useI18n()
if (typeof document !== 'undefined') document.documentElement.classList.add('admin-dark')
app.use(createPinia())
app.use(PrimeVue, {
  theme: {
    preset: AdminPreset,
    options: { darkModeSelector: '.admin-dark' },
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
