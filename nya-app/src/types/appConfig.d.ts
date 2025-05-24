import type { StorageConfig } from '@jsxiaosi/utils/es/window/storage/types';

export interface AppConfig {
    collapseMenu: boolean;
    themeMode: 'light' | 'dark';
    primaryColor: string;
    StorageConfig: StorageConfig;
    drawerSidebar?: boolean;
}