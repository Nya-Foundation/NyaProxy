import { getAuth } from '@/api/dashboardApi';
import { useAuthStore } from '@/stores/modules/auth';
import { close, start } from '@/utils/nprogress';
import type { RouteRecordRaw } from 'vue-router';
import { createRouter, createWebHistory } from 'vue-router';

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    redirect: '/dashboard',
    component: () => import('@/layout/index.vue'),
    meta: {
      auth: true
    },
    children: [
      {
        path: '/dashboard',
        name: 'Dashboard',
        component: () => import('@/pages/dashboard/index.vue'),
        meta: {
          title: 'Dashboard',
          icon: 'DataBoard'
        }
      },
      {
        path: '/nekoconf',
        name: 'NekoConf',
        component: () => import('@/pages/nekoconf/index.vue'),
        meta: {
          title: 'NekoConf',
          icon: 'Tools'
        }
      }
    ]
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/login/index.vue')
  },
  {
    path: '/:any(.*)',
    name: '404',
    component: () => import('@/pages/404/index.vue')
  }
];

const whiteList = ['/login', '/404'];

// Paths that should be handled by backend, not frontend router
const backendPaths = ['/config', '/dashboard/docs', '/config/docs'];

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
});

// Add a global navigation guard to handle backend paths
if (typeof window !== 'undefined') {
  const originalPush = router.push;
  const originalReplace = router.replace;

  // Override push method
  router.push = function (to: any) {
    const path = typeof to === 'string' ? to : to.path;
    if (path && backendPaths.some(bp => path.startsWith(bp))) {
      window.location.href = path;
      return Promise.resolve();
    }
    return originalPush.call(this, to);
  };

  // Override replace method
  router.replace = function (to: any) {
    const path = typeof to === 'string' ? to : to.path;
    if (path && backendPaths.some(bp => path.startsWith(bp))) {
      window.location.replace(path);
      return Promise.resolve();
    }
    return originalReplace.call(this, to);
  };
}

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
