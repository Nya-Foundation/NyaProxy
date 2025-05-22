import Cookies from "js-cookie";

const TokenKey = "nyaproxy_api_key";

export function getToken() {
  return Cookies.get(TokenKey);
}

export function setToken(token: string, cookieExpires: any) {
  return Cookies.set(TokenKey, token, { sameSite: "Strict", expires: cookieExpires ?? 7 });
}

export function removeToken() {
  return Cookies.remove(TokenKey);
}
