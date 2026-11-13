/** Auth endpoints (docs/api.md). Passwords, codes and tokens are never logged or stored. */

import { apiFetch } from '../../lib/api';
import { CSRF_COOKIE, readCookie } from '../../lib/session';

export type Role = 'owner' | 'staff';

export type User = {
  id: number;
  name: string;
  mobile: string;
  email: string | null;
  role: Role;
  is_active: boolean;
  must_change_password: boolean;
  totp_enabled: boolean;
  last_login_at: string | null;
  deactivated_at: string | null;
  created_at: string;
  permissions: string[];
};

export type SignedIn = {
  status: 'ok';
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: User;
};

export type Challenge = {
  status: 'totp_required' | 'totp_setup_required';
  challenge_token: string;
};

export type TotpSetup = { secret: string; otpauth_uri: string; qr_svg: string };
export type Enrolled = SignedIn & { recovery_codes: string[] };

const BASE = '/api/v1/auth';

export function login(loginId: string, password: string) {
  return apiFetch<SignedIn | Challenge>(`${BASE}/login`, {
    method: 'POST',
    json: { login: loginId, password },
    auth: false,
  });
}

export function submitTotp(
  challengeToken: string,
  entry: { code: string } | { recovery_code: string },
) {
  return apiFetch<SignedIn>(`${BASE}/totp`, {
    method: 'POST',
    json: { challenge_token: challengeToken, ...entry },
    auth: false,
  });
}

export function startTotpSetup(challengeToken: string) {
  return apiFetch<TotpSetup>(`${BASE}/totp/setup`, {
    method: 'POST',
    json: { challenge_token: challengeToken },
    auth: false,
  });
}

export function confirmTotp(challengeToken: string, code: string) {
  return apiFetch<Enrolled>(`${BASE}/totp/confirm`, {
    method: 'POST',
    json: { challenge_token: challengeToken, code },
    auth: false,
  });
}

/** Uses the httpOnly refresh cookie plus the double-submit CSRF token. */
export function refreshSession() {
  const csrf = readCookie(CSRF_COOKIE);
  return apiFetch<SignedIn>(`${BASE}/refresh`, {
    method: 'POST',
    headers: csrf ? { 'X-CSRF-Token': csrf } : {},
    auth: false,
  });
}

export function logout() {
  return apiFetch<void>(`${BASE}/logout`, { method: 'POST' });
}

export function changePassword(currentPassword: string, newPassword: string) {
  return apiFetch<void>(`${BASE}/change-password`, {
    method: 'POST',
    json: { current_password: currentPassword, new_password: newPassword },
  });
}
