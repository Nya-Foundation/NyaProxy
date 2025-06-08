import router from '@/router';
import { getToken, removeToken } from '@/utils/auth';
import type { AxiosError, AxiosRequestConfig, AxiosResponse } from 'axios';
import axios from 'axios';

// 创建axios实例
const instance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api'
});

// 请求拦截器
instance.interceptors.request.use(
  (config: AxiosRequestConfig): any => {
    // 可在请求发送前对config进行修改，如添加请求头等
    const token = getToken();
    const headers = config.headers || {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    config.headers = headers;
    return config;
  },
  (error: AxiosError) => {
    // 处理请求错误
    return Promise.reject(error);
  }
);

// 响应拦截器
instance.interceptors.response.use(
  (response: AxiosResponse) => {
    // 对响应数据进行处理
    return response;
  },
  (error: AxiosError) => {
    // 处理响应错误
    if (error.response?.status === 401 || error.response?.status === 403) {
      removeToken();
      if (router.currentRoute.value.path !== '/login') {
        router.push({ path: '/login', query: { return_path: router.currentRoute.value.path } });
      }
    }
    return Promise.reject(error);
  }
);

export default instance;
