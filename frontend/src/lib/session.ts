/**
 * The signed-in session, held in memory only (docs/security.md): the 15-minute access token
 * never touches localStorage. On page load the app restores it from the httpOnly refresh
 * cookie via POST /api/v1/auth/refresh.
 */

let accessToken: string | null = null;

/** Refreshes the access token; resolves true when a new one was stored. */
type RefreshHandler = () => Promise<boolean>;
let refreshHandler: RefreshHandler | null = null;
let expiredHandler: (() => void) | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function setRefreshHandler(handler: RefreshHandler | null): void {
  refreshHandler = handler;
}

export function getRefreshHandler(): RefreshHandler | null {
  return refreshHandler;
}

/** Called when a request is refused and the session cannot be refreshed. */
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  expiredHandler = handler;
}

export function notifySessionExpired(): void {
  expiredHandler?.();
}

export const CSRF_COOKIE = 'arms_csrf';

export function readCookie(name: string): string | null {
  for (const part of document.cookie.split(';')) {
    const [key, ...rest] = part.trim().split('=');
    if (key === name) return decodeURIComponent(rest.join('='));
  }
  return null;
}
