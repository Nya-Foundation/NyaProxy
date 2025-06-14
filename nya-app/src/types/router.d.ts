import { RouteRecordRaw } from 'vue-router';

interface AppRouteRecordRaw extends Omit<RouteRecordRaw, 'children'> {
  meta?: {
    title?: string;
    icon?: string;
    alwaysShow?: boolean;
    activeMenu?: string;
  };
  children?: AppRouteRecordRaw[];
}
