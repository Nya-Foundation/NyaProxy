import Cookies from 'js-cookie';

const TokenKey = 'nyaproxy_api_key';

export function getToken() {
  return Cookies.get(TokenKey);
}

export function setToken(token: string, cookieExpires: any = 7) {
  return Cookies.set(TokenKey, token, { sameSite: 'Strict', expires: cookieExpires });
}

export function removeToken() {
  return Cookies.remove(TokenKey);
}
