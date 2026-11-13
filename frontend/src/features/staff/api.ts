import { apiFetch } from '../../lib/api';
import type { User } from '../auth/api';

export type PageOf<T> = { items: T[]; total: number; page: number; page_size: number };

export type PermissionInfo = {
  code: string;
  label: string;
  grantable: boolean;
  staff_default: boolean;
};

export type StaffInput = { name: string; mobile: string; email: string | null };

const BASE = '/api/v1/users';

export function listStaff(params: {
  page: number;
  search: string;
  status: 'active' | 'inactive' | 'all';
}) {
  const query = new URLSearchParams({ page: String(params.page), page_size: '20', role: 'staff' });
  if (params.search.trim()) query.set('search', params.search.trim());
  if (params.status !== 'all') query.set('is_active', String(params.status === 'active'));
  return apiFetch<PageOf<User>>(`${BASE}?${query.toString()}`);
}

export function countActiveStaff() {
  return apiFetch<PageOf<User>>(`${BASE}?role=staff&is_active=true&page_size=1`).then(
    (page) => page.total,
  );
}

export function createStaff(input: StaffInput) {
  return apiFetch<{ user: User; temporary_password: string }>(BASE, {
    method: 'POST',
    json: input,
  });
}

export function updateStaff(id: number, input: StaffInput) {
  return apiFetch<User>(`${BASE}/${id}`, { method: 'PATCH', json: input });
}

export function deactivateStaff(id: number, reason: string) {
  return apiFetch<User>(`${BASE}/${id}/deactivate`, {
    method: 'POST',
    json: { reason: reason.trim() || null },
  });
}

export function reactivateStaff(id: number) {
  return apiFetch<User>(`${BASE}/${id}/reactivate`, { method: 'POST' });
}

export function resetStaffPassword(id: number) {
  return apiFetch<{ temporary_password: string }>(`${BASE}/${id}/reset-password`, {
    method: 'POST',
  });
}

export function setStaffPermissions(id: number, permissions: string[]) {
  return apiFetch<User>(`${BASE}/${id}/permissions`, { method: 'PUT', json: { permissions } });
}

export function permissionCatalogue() {
  return apiFetch<{ items: PermissionInfo[] }>('/api/v1/permissions').then((r) => r.items);
}
