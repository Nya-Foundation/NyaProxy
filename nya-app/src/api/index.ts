import { get } from "@/utils/methods";

export async function getAuth(): Promise<any> {
  const res = await get<any>("/dashboard/api/history");
  return res;
}