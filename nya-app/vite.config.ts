import { fileURLToPath, URL } from 'node:url';

import vue from '@vitejs/plugin-vue';
import vueJsx from '@vitejs/plugin-vue-jsx';
import { defineConfig } from 'vite';

import AutoImport from 'unplugin-auto-import/vite';
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers';
import Components from 'unplugin-vue-components/vite';

// https://vite.dev/config/
export default defineConfig({
  base: './',
  build: {
    outDir: '../nya/static', // Build frontend to backend static folder
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          // Vue core libraries
          vue: ['vue', 'vue-router', 'pinia'],
          // UI component library
          'element-plus': ['element-plus', '@element-plus/icons-vue'],
          // Chart library
          charts: ['echarts'],
          // Utility libraries
          utils: ['lodash-es', '@vueuse/core', 'dayjs', 'axios'],
          // Other small libraries
          libs: ['js-cookie', 'nprogress', '@jsxiaosi/utils']
        }
      }
    }
  },
  plugins: [
    vue(),
    vueJsx(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: 'src/auto-imports.d.ts'
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts'
    })
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern-compiler',
        charset: false,
        additionalData: `
        @use "@/styles/index.scss" as *;
        @use "@/styles/variables/theme/index.scss" as *;
        @use "@/styles/variables/index.scss" as *;
        `
      }
    }
  },
  server: {
    host: true,
    port: 5140,
    strictPort: false,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api/, '')
      }
    }
  }
});
