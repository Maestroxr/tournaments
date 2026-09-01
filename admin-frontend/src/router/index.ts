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
      name: 'tournament-detail',
      component: () => import('@/pages/TournamentDetailView.vue'),
      props: true,
      meta: {
        breadcrumb: ((route: RouteLocationNormalized) => [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Tournaments', to: '/tournaments' },
          { label: route.params.id === 'test-1' ? 'test 1' : String(route.params.id) },
        ]) satisfies BreadcrumbFactory,
      },
    },
    {
      path: '/tournaments/:id/attendees',
      name: 'tournament-attendees',
      component: () => import('@/pages/AttendeesView.vue'),
      meta: {
        breadcrumb: ((route: RouteLocationNormalized) => [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Tournaments', to: '/tournaments' },
          { label: String(route.params.id) },
          { label: 'Attendees' },
        ]) satisfies BreadcrumbFactory,
      },
    },
    {
      path: '/tournaments/:id/progress',
      name: 'tournament-progress',
      component: () => import('@/pages/TournamentProgressView.vue'),
      props: true,
      meta: {
        breadcrumb: ((route: RouteLocationNormalized) => [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Tournaments', to: '/tournaments' },
          { label: String(route.params.id) },
          { label: 'Progress' },
        ]) satisfies BreadcrumbFactory,
      },
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
      path: '/transfers',
      name: 'transfers',
      component: () => import('@/pages/TransfersView.vue'),
      meta: {
        breadcrumb: [
          { label: 'Dashboard', to: '/dashboard' },
          { label: 'Transfers' },
        ] satisfies BreadcrumbItem[],
      },
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
