import { get } from '@/utils/methods';

export async function getConfig(): Promise<any> {
  const res = await get<any>('/config/api/config');
  return res;
}
