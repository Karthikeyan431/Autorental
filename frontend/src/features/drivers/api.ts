/** Driver endpoints (docs/api.md "Drivers"). */

import { apiFetch } from '../../lib/api';
import type { PageOf } from '../staff/api';

export type UserRef = { id: number; name: string };

export type KycStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'approved'
  | 'rejected'
  | 'resubmission_required'
  | 'expired';

export type Driver = {
  id: number;
  code: string;
  full_name: string;
  mobile: string;
  alt_mobile: string | null;
  address: string;
  date_of_birth: string;
  emergency_name: string | null;
  emergency_mobile: string | null;
  photo_document_id: number | null;
  account_status: 'active' | 'suspended' | 'inactive';
  status_reason: string | null;
  payment_rhythm: 'daily' | 'weekly';
  registered_at: string;
  created_by: UserRef;
  managed_by: UserRef;
  managed_since: string | null;
  identity_status: KycStatus | null;
  licence_status: KycStatus | null;
  can_edit: boolean;
  can_view_kyc: boolean;
};

export type DriverListItem = Pick<
  Driver,
  | 'id'
  | 'code'
  | 'full_name'
  | 'mobile'
  | 'account_status'
  | 'photo_document_id'
  | 'created_by'
  | 'managed_by'
  | 'identity_status'
  | 'licence_status'
>;

export type DriverInput = {
  full_name: string;
  mobile: string;
  alt_mobile: string | null;
  address: string;
  date_of_birth: string;
  emergency_name: string | null;
  emergency_mobile: string | null;
  payment_rhythm: 'daily' | 'weekly';
};

export type ManagerHistoryRow = {
  id: number;
  staff: UserRef;
  from_at: string;
  to_at: string | null;
  changed_by: UserRef;
  reason: string | null;
};

export type TimelineEntry = {
  id: number;
  at: string;
  action: string;
  entity_type: string;
  entity_id: number | null;
  actor: UserRef | null;
  reason: string | null;
};

export type DriverFilters = {
  page: number;
  search: string;
  status: '' | 'active' | 'suspended' | 'inactive';
  managedBy: string; // '' = anyone, 'me' = managed by me, or a user id
  kyc: '' | 'verified' | 'not_verified';
};

const BASE = '/api/v1/drivers';

export function listDrivers(filters: DriverFilters) {
  const query = new URLSearchParams({ page: String(filters.page), page_size: '20' });
  if (filters.search.trim()) query.set('search', filters.search.trim());
  if (filters.status) query.set('status', filters.status);
  if (filters.managedBy === 'me') query.set('mine', 'true');
  else if (filters.managedBy) query.set('managed_by', filters.managedBy);
  if (filters.kyc) query.set('kyc', filters.kyc);
  return apiFetch<PageOf<DriverListItem>>(`${BASE}?${query.toString()}`);
}

export function fetchManagers() {
  return apiFetch<UserRef[]>(`${BASE}/managers`);
}

export function fetchDriver(id: number) {
  return apiFetch<Driver>(`${BASE}/${id}`);
}

export function createDriver(input: DriverInput) {
  return apiFetch<Driver>(BASE, { method: 'POST', json: input });
}

export function updateDriver(id: number, input: Partial<DriverInput>) {
  return apiFetch<Driver>(`${BASE}/${id}`, { method: 'PATCH', json: input });
}

export function uploadDriverPhoto(id: number, file: Blob, filename = 'photo.jpg') {
  const body = new FormData();
  body.append('file', file, filename);
  return apiFetch<Driver>(`${BASE}/${id}/photo`, { method: 'POST', body });
}

export function changeManager(id: number, staffId: number, reason: string) {
  return apiFetch<Driver>(`${BASE}/${id}/manager`, {
    method: 'POST',
    json: { staff_id: staffId, reason },
  });
}

export function fetchManagerHistory(id: number) {
  return apiFetch<ManagerHistoryRow[]>(`${BASE}/${id}/manager-history`);
}

export function fetchTimeline(id: number) {
  return apiFetch<TimelineEntry[]>(`${BASE}/${id}/timeline`);
}

export function fetchDocumentBlob(documentId: number) {
  return apiFetch<Blob>(`/api/v1/documents/${documentId}/content`, { responseType: 'blob' });
}
