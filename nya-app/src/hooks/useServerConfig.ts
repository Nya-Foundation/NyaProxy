import { get } from '@/utils/methods';
import { computed, readonly, ref } from 'vue';

const serverPort = ref<number>(8080); // Default port
const serverHost = ref<string>('localhost'); // Default host
const loading = ref(false);
const error = ref<string | null>(null);

/**
 * Hook for getting server port configuration
 */
export const useServerConfig = () => {
  // Convert host address for local access
  const normalizeHost = (host: string): string => {
    // Convert 0.0.0.0 to localhost for browser access
    return host === '0.0.0.0' ? 'localhost' : host;
  };

  // Fetch server configuration from backend API
  const fetchServerConfig = async () => {
    if (loading.value) return;

    loading.value = true;
    error.value = null;

    try {
      // Try to get server configuration from backend API
      const response = await get('/config/api/apps/NyaProxy/config');
      if (response && typeof response === 'object') {
        const config = response as { server?: { port?: number; host?: string } };
        if (config.server?.port) {
          serverPort.value = config.server.port;
        }
        if (config.server?.host) {
          serverHost.value = normalizeHost(config.server.host);
        }
      }
    } catch (err: any) {
      error.value = err.message ?? 'Failed to fetch server configuration';
      console.warn('Failed to fetch server configuration, using defaults:', err);
      // Keep default values (localhost:8080) if API fails
    } finally {
      loading.value = false;
    }
  };

  // Get current server port
  const getServerPort = () => serverPort.value;

  // Get current server host
  const getServerHost = () => serverHost.value;

  // Get base URL with current host and port
  const getBaseUrl = computed(() => `http://${serverHost.value}:${serverPort.value}`);

  // Get API base URL
  const getApiBaseUrl = computed(() => `${getBaseUrl.value}/api`);

  // Generate API endpoint URL
  const getApiEndpointUrl = (endpointName: string) => {
    return `${getApiBaseUrl.value}/${endpointName}`;
  };

  return {
    serverPort: readonly(serverPort),
    serverHost: readonly(serverHost),
    loading: readonly(loading),
    error: readonly(error),
    fetchServerConfig,
    getServerPort,
    getServerHost,
    getBaseUrl,
    getApiBaseUrl,
    getApiEndpointUrl
  };
};
