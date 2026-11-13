/** Auto endpoints (docs/api.md "Vehicles"). Money is integer paise. */

import { apiFetch } from '../../lib/api';
import type { UserRef } from '../drivers/api';
import type { PageOf } from '../staff/api';

export type VehicleStatus = 'available' | 'rented' | 'maintenance' | 'inactive';
export type FuelType = 'cng' | 'lpg' | 'petrol' | 'diesel' | 'electric';
export type PaperKind = 'insurance' | 'fitness' | 'permit' | 'pollution';
export type PaperState = 'ok' | 'expiring' | 'expired';

export type Paper = {
  id: number;
  kind: PaperKind;
  number: string | null;
  valid_from: string | null;
  valid_until: string;
  document_id: number | null;
  document_mime_type: string | null;
  state: PaperState;
  recorded_by: UserRef | null;
  created_at: string;
};

export type Vehicle = {
  id: number;
  registration_number: string;
  make: string;
  model: string;
  year: number | null;
  fuel_type: FuelType | null;
  status: VehicleStatus;
  /** Only an available auto can be given to a driver (checked again when an agreement starts). */
  selectable: boolean;
  notes: string | null;
  /** The current paper of each kind. */
  papers: Paper[];
  created_by: UserRef | null;
  created_at: string;
};

export type VehicleInput = {
  registration_number: string;
  make: string;
  model: string;
  year: number | null;
  fuel_type: FuelType | null;
  notes: string | null;
};

export type VehicleSummary = {
  available: number;
  rented: number;
  maintenance: number;
  inactive: number;
  papers_expiring: number;
  papers_expired: number;
};

export type Maintenance = {
  id: number;
  vehicle_id: number;
  started_on: string;
  ended_on: string | null;
  description: string;
  cost_paise: number | null;
  recorded_by: UserRef | null;
  created_at: string;
};

export type MaintenanceInput = {
  started_on: string;
  ended_on: string | null;
  description: string;
  cost_paise: number | null;
};

export type VehicleFilters = { page: number; search: string; status: VehicleStatus | '' };

const BASE = '/api/v1/vehicles';

export function listVehicles(filters: VehicleFilters) {
  const query = new URLSearchParams({ page: String(filters.page), page_size: '20' });
  if (filters.search.trim()) query.set('search', filters.search.trim());
  if (filters.status) query.set('status', filters.status);
  return apiFetch<PageOf<Vehicle>>(`${BASE}?${query.toString()}`);
}

export function fetchVehicleSummary() {
  return apiFetch<VehicleSummary>(`${BASE}/summary`);
}

export function fetchVehicle(id: number) {
  return apiFetch<Vehicle>(`${BASE}/${id}`);
}

export function createVehicle(input: VehicleInput) {
  return apiFetch<Vehicle>(BASE, { method: 'POST', json: input });
}

export function updateVehicle(id: number, input: Partial<VehicleInput>) {
  return apiFetch<Vehicle>(`${BASE}/${id}`, { method: 'PATCH', json: input });
}

export function changeVehicleStatus(id: number, status: VehicleStatus, reason: string | null) {
  return apiFetch<Vehicle>(`${BASE}/${id}/status`, { method: 'POST', json: { status, reason } });
}

export function fetchPapers(id: number) {
  return apiFetch<Paper[]>(`${BASE}/${id}/compliance`);
}

export function addPaper(
  id: number,
  input: { kind: PaperKind; number: string; valid_from: string; valid_until: string },
  file: { blob: Blob; name: string } | null,
) {
  const body = new FormData();
  body.append('kind', input.kind);
  body.append('valid_until', input.valid_until);
  if (input.number) body.append('number', input.number);
  if (input.valid_from) body.append('valid_from', input.valid_from);
  if (file) body.append('file', file.blob, file.name);
  return apiFetch<Paper>(`${BASE}/${id}/compliance`, { method: 'POST', body });
}

export function fetchMaintenance(id: number) {
  return apiFetch<Maintenance[]>(`${BASE}/${id}/maintenance`);
}

export function addMaintenance(id: number, input: MaintenanceInput) {
  return apiFetch<Maintenance>(`${BASE}/${id}/maintenance`, { method: 'POST', json: input });
}
