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
      redirect: () => {
        const auth = useAuthStore()
        return auth.isLoggedIn ? '/dashboard' : '/login'
      },
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

router.beforeEach((to, from, next) => {
  const auth = useAuthStore()
  if (to.path === '/login') {
    if (auth.isLoggedIn) next('/dashboard')
    else next()
  } else if (!auth.isLoggedIn) {
    next('/login')
  } else {
    next()
  }
})

export default router
