import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppLayout from '@/layouts/AppLayout.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/pages/Register.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/pages/Dashboard.vue'),
      },
      {
        path: 'kb',
        name: 'KBList',
        component: () => import('@/pages/kb/Index.vue'),
      },
      {
        path: 'kb/:id',
        name: 'KBDocument',
        component: () => import('@/pages/kb/Index.vue'),
      },
      {
        path: 'chat',
        name: 'ChatList',
        component: () => import('@/pages/chat/Index.vue'),
      },
      {
        path: 'chat/:id',
        name: 'ChatDetail',
        component: () => import('@/pages/chat/Index.vue'),
      },
      {
        path: 'admin/providers',
        name: 'AdminProviders',
        component: () => import('@/pages/admin/Providers.vue'),
        meta: { requiresAdmin: true },
      },
      {
        path: 'admin/dashboard',
        name: 'AdminDashboard',
        component: () => import('@/pages/admin/Dashboard.vue'),
        meta: { requiresAdmin: true },
      },
      {
        path: 'admin/users',
        name: 'AdminUsers',
        component: () => import('@/pages/admin/Users.vue'),
        meta: { requiresAdmin: true },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()

  // Try to restore session on first navigation
  if (!authStore.isAuthenticated) {
    await authStore.fetchUser()
  }

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
  } else if (to.name === 'Login' && authStore.isAuthenticated) {
    next({ name: 'Dashboard' })
  } else if (to.meta.requiresAdmin && authStore.user?.role !== 'admin') {
    next({ name: 'Dashboard' })
  } else {
    next()
  }
})

export default router
