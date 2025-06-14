import { getToken, removeToken, setToken } from '@/utils/auth';
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getToken() ?? null);

  function login(token: string) {
    setToken(token, 7);
  }

  function logout() {
    removeToken();
  }

  const isAuth = computed(() => !!token.value);

  return {
    token,
    login,
    logout,
    isAuth
  };
});
