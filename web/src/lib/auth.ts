export type UserInfo = {
  id: number;
  username: string;
  email: string | null;
  role: string;
  risk_profile: string;
  is_active: boolean;
};

export function getUserFromCookie(): UserInfo | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)finn_auth_user=([^;]*)/);
  if (!match) return null;
  try {
    return JSON.parse(decodeURIComponent(match[1]));
  } catch {
    return null;
  }
}

export function setUserCookie(user: UserInfo | null): void {
  if (typeof document === "undefined") return;
  if (user) {
    const expires = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toUTCString();
    document.cookie = `finn_auth_user=${encodeURIComponent(JSON.stringify(user))}; path=/; expires=${expires}; SameSite=Lax`;
  } else {
    document.cookie = "finn_auth_user=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
  }
}
