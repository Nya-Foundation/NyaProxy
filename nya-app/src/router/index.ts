import { getAuth } from '@/api';
import { useAuthStore } from '@/stores/auth';
import { close, start } from '@/utils/nprogress';
import type { RouteRecordRaw } from 'vue-router';
import { createRouter, createWebHistory } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    redirect: '/dashboard',
    component: () => import('@/layout/index.vue'),
    meta: {
      auth: true,
      title: 'Home'
    },
    children: [
      {
        path: '/dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue'),
        meta: {
          title: 'Dashboard'
        }
      },
      {
        path: '/config',
        name: 'Config',
        component: () => import('@/views/nekoconf/index.vue'),
        meta: {
          title: 'Neko Config'
        }
      }
    ]
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue')
  },
  {
    path: '/:any(.*)',
    name: '404',
    component: () => import('@/views/404/index.vue')
  }
];

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
});

router.beforeEach(async (to, from, next) => {
  const store = useAuthStore();
  start();

  if (to.meta.auth) {
    try {
      await getAuth();
      next();
    } catch (e) {
      console.log(e);
      store.logout();
      next({ name: 'Login', query: { return_path: to.fullPath } });
    }
  } else {
    next();
  }
});

router.afterEach(() => {
  close();
});

export default router;
