import { get, post } from '@/utils/methods';

export async function getAuth(): Promise<any> {
  const res = await get<any>('/dashboard/api/history');
  return res;
}

export async function getMetrics(): Promise<any> {
  const res = await get<any>('/dashboard/api/metrics');
  return res;
}

export async function getHistory(): Promise<any> {
  const res = await get<any>('/dashboard/api/history');
  return res;
}

export async function getAnalytics(time: string, api_name?: string, key_id?: string): Promise<any> {
  const res = await get<any>('/dashboard/api/analytics', { time_range: time, api_name, key_id });
  return res;
}

export async function getQuene(): Promise<any> {
  const res = await get<any>('/dashboard/api/queue');
  return res;
}

export async function getKeyUsage(): Promise<any> {
  const res = await get<any>('/dashboard/api/key-usage');
  return res;
}

export async function clearQueue(api_name: string): Promise<any> {
  const res = await post<any>(`/dashboard/api/queue/clear/${api_name}`);
  return res;
}
