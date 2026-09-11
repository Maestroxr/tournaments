import { createRouter, createWebHistory, type RouteLocationNormalized } from 'vue-router'
import { useAuthStore } from '@/stores/auth.ts'
import Login from '@/pages/LoginView.vue'
import type { BreadcrumbItem } from '@/components/AppBreadcrumb.vue'

type BreadcrumbFactory = (route: RouteLocationNormalized) => BreadcrumbItem[]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/pages/DashboardView.vue'),
      meta: { breadcrumb: [{ label: 'Dashboard' }] satisfies BreadcrumbItem[] },
    },
    { path: '/login', name: 'login', component: Login },
    {
      path: '/tournaments',
      name: 'tournaments',
      component: () => import('@/pages/TournamentsView.vue'),
      meta: {
        breadcrumb: [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Tournaments' },
        ] satisfies BreadcrumbItem[],
      },
    },
    {
      path: '/tournaments/new',
      name: 'tournaments-create',
      component: () => import('@/pages/TournamentCreateView.vue'),
      meta: {
        breadcrumb: [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Tournaments', to: '/tournaments' },
          { label: 'Create Tournament' },
        ] satisfies BreadcrumbItem[],
      },
    },
    {
      path: '/tournaments/:id',
      component: () => import('@/layouts/TournamentWorkspaceLayout.vue'),
      props: true,
      meta: {
        breadcrumb: ((route: RouteLocationNormalized) => [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Tournaments', to: '/tournaments' },
          { label: route.params.id === 'test-1' ? 'test 1' : String(route.params.id) },
        ]) satisfies BreadcrumbFactory,
      },
      children: [
        {
          path: '',
          redirect: (to) => ({ name: 'tournament-detail', params: to.params }),
        },
        {
          path: 'overview',
          name: 'tournament-detail',
          component: () => import('@/pages/TournamentDetailView.vue'),
          props: true,
        },
        {
          path: 'settings',
          name: 'tournament-settings',
          component: () => import('@/pages/TournamentDetailView.vue'),
          props: true,
        },
        {
          path: 'players',
          name: 'tournament-players',
          component: () => import('@/pages/AttendeesView.vue'),
        },
        {
          path: 'draw',
          redirect: (to) => ({ name: 'tournament-players', params: to.params }),
        },
        {
          path: 'live',
          name: 'tournament-live',
          component: () => import('@/pages/TournamentProgressView.vue'),
          beforeEnter: (to) => {
            if (to.query.view === 'matches')
              return { name: 'tournament-bracket', params: to.params }
            if (to.query.view === 'standings')
              return { name: 'tournament-standings', params: to.params }
          },
        },
        {
          path: 'bracket',
          name: 'tournament-bracket',
          component: () => import('@/pages/TournamentProgressView.vue'),
        },
        {
          path: 'standings',
          name: 'tournament-standings',
          component: () => import('@/pages/TournamentProgressView.vue'),
        },
        {
          path: 'results',
          name: 'tournament-results',
          component: () => import('@/pages/TournamentProgressView.vue'),
        },
        {
          path: 'attendees',
          redirect: (to) => ({ name: 'tournament-players', params: to.params }),
        },
        {
          path: 'progress',
          name: 'tournament-progress',
          redirect: (to) => ({ name: 'tournament-bracket', params: to.params }),
        },
      ],
    },
    {
      path: '/users',
      name: 'users',
      component: () => import('@/pages/UsersView.vue'),
      meta: {
        breadcrumb: [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Users' },
        ] satisfies BreadcrumbItem[],
      },
    },
    {
      path: '/direct-play',
      name: 'direct-play',
      component: () => import('@/pages/DirectPlayView.vue'),
      meta: {
        breadcrumb: [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Direct Play' },
        ] satisfies BreadcrumbItem[],
      },
    },
    {
      path: '/transfers',
      component: () => import('@/layouts/TransfersWorkspaceLayout.vue'),
      meta: {
        breadcrumb: [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Transfers' },
        ] satisfies BreadcrumbItem[],
      },
      children: [
        {
          path: '',
          name: 'transfers',
          component: () => import('@/pages/TransfersView.vue'),
        },
        {
          path: 'finance',
          name: 'transfers-finance',
          component: () => import('@/pages/FinancialOverviewView.vue'),
        },
        {
          path: 'payments',
          name: 'transfers-payments',
          component: () => import('@/pages/PaymentsView.vue'),
        },
        {
          path: 'catalog',
          name: 'transfers-catalog',
          component: () => import('@/pages/CatalogView.vue'),
        },
      ],
    },
    {
      path: '/users/new',
      name: 'users-create',
      component: () => import('@/pages/UserCreateView.vue'),
      meta: {
        breadcrumb: [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Users', to: '/users' },
          { label: 'Create' },
        ] satisfies BreadcrumbItem[],
      },
    },
    {
      path: '/users/:id/edit',
      name: 'users-edit',
      component: () => import('@/pages/UserEditView.vue'),
      props: true,
      meta: {
        breadcrumb: ((route: RouteLocationNormalized) => [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Users', to: '/users' },
          { label: String(route.params.id) },
        ]) satisfies BreadcrumbFactory,
      },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/pages/NotFoundView.vue'),
      meta: { breadcrumb: [{ label: '404' }] satisfies BreadcrumbItem[] },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.checked) await auth.fetchMe()
  if (to.path === '/') return auth.isLoggedIn ? '/dashboard' : '/login'
  if (to.path === '/login') {
    if (auth.isAdmin) return '/dashboard'
    return
  }
  if (!auth.isLoggedIn) return { path: '/login', query: { next: to.fullPath } }
  if (!auth.isAdmin) return { path: '/login', query: { reason: 'admin-required', next: to.fullPath } }
})

export default router
