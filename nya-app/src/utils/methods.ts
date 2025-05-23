import instance from './http';

// 封装GET请求
export function get<T>(url: string, params?: any): Promise<T> {
  return instance
    .get<T>(url, { params })
    .then(response => response.data)
    .catch(error => {
      throw error;
    });
}

// 封装POST请求
export function post<T>(url: string, data?: any): Promise<T> {
  return instance
    .post<T>(url, data)
    .then(response => response.data)
    .catch(error => {
      throw error;
    });
}

// put
export function put<T>(url: string, data?: any): Promise<T> {
  return instance
    .put<T>(url, data)
    .then(response => response.data)
    .catch(error => {
      throw error;
    });
}
//delete
export function del<T>(url: string): Promise<T> {
  return instance
    .delete<T>(url)
    .then(response => response.data)
    .catch(error => {
      throw error;
    });
}
