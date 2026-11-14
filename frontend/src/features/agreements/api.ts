/** Agreement and rent endpoints (docs/api.md "Agreements", "Rent"). Money is integer paise. */

import { apiFetch } from '../../lib/api';
import type { UserRef } from '../drivers/api';
import type { PageOf } from '../staff/api';

export type AgreementStatus = 'draft' | 'active' | 'ended' | 'cancelled';

export type Agreement = {
  id: number;
  agreement_no: string;
  status: AgreementStatus;
  driver: { id: number; code: string; full_name: string; managed_by: UserRef | null };
  vehicle: { id: number; registration_number: string; make: string; model: string; status: string };
  start_date: string;
  end_date: string | null;
  daily_rent_paise: number;
  advance_required_paise: number;
  terms_version: string;
  signed_document_id: number | null;
  created_by: UserRef | null;
  created_at: string;
  activated_by: UserRef | null;
  activated_at: string | null;
  ended_by: UserRef | null;
  ended_at: string | null;
  end_reason: string | null;
  cancelled_by: UserRef | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  /** Q1: an ended agreement's auto can start again from the day after the return day. */
  vehicle_available_from: string | null;
};

export type AgreementInput = {
  driver_id: number;
  vehicle_id: number;
  start_date: string;
  daily_rent_paise: number;
  advance_required_paise: number;
};

export type EligibilityReason = { code: string; message: string };

export type Eligibility = {
  ok: boolean;
  reasons: EligibilityReason[];
  vehicle_available_from: string | null;
  max_backdate_days: number | null;
};

export type AgreementFilters = {
  page: number;
  status: AgreementStatus | '';
  search: string;
  driverId?: number;
};

export type DayStatus = 'paid' | 'part_paid' | 'unpaid' | 'waived';

export type LedgerRow = {
  charge_id: number;
  agreement_id: number;
  agreement_no: string;
  rent_date: string;
  due_at: string;
  charge_paise: number;
  adjustments_paise: number;
  pending_adjustments_paise: number;
  allocated_paise: number;
  awaiting_approval_paise: number;
  balance_paise: number;
  status: DayStatus;
  is_overdue: boolean;
  pending_adjustment_ids: number[];
};

export type Ledger = {
  driver_id: number;
  as_of: string;
  rows: LedgerRow[];
  totals: {
    charge_paise: number;
    adjustments_paise: number;
    allocated_paise: number;
    balance_paise: number;
  };
  outstanding_paise: number;
  overdue_paise: number;
};

export type Adjustment = {
  id: number;
  rent_charge_id: number;
  rent_date: string;
  driver_id: number;
  amount_paise: number;
  reason: string;
  status: 'pending' | 'approved' | 'rejected';
  requested_by: UserRef | null;
  created_at: string;
  decided_by: UserRef | null;
  decided_at: string | null;
  decision_reason: string | null;
};

export type RentSummary = {
  scope: 'all' | 'own';
  as_of: string;
  rent_expected_today_paise: number;
  active_agreements: number;
  overdue_drivers: number;
  overdue_paise: number;
  adjustments_pending: number;
};

export type OverdueRow = {
  driver_id: number;
  driver_code: string;
  driver_name: string;
  managed_by: UserRef;
  overdue_paise: number;
  outstanding_paise: number;
  awaiting_approval_paise: number;
  oldest_overdue_date: string;
  days_overdue: number;
};

const BASE = '/api/v1/agreements';

export function listAgreements(filters: AgreementFilters) {
  const query = new URLSearchParams({ page: String(filters.page), page_size: '20' });
  if (filters.status) query.set('status', filters.status);
  if (filters.search.trim()) query.set('search', filters.search.trim());
  if (filters.driverId !== undefined) query.set('driver_id', String(filters.driverId));
  return apiFetch<PageOf<Agreement>>(`${BASE}?${query.toString()}`);
}

export function fetchAgreement(id: number) {
  return apiFetch<Agreement>(`${BASE}/${id}`);
}

export function fetchEligibility(driverId: number, vehicleId: number, startDate: string) {
  const query = new URLSearchParams({
    driver_id: String(driverId),
    vehicle_id: String(vehicleId),
    start_date: startDate,
  });
  return apiFetch<Eligibility>(`${BASE}/eligibility?${query.toString()}`);
}

export function createAgreement(input: AgreementInput) {
  return apiFetch<Agreement>(BASE, { method: 'POST', json: input });
}

export function activateAgreement(id: number) {
  return apiFetch<Agreement>(`${BASE}/${id}/activate`, { method: 'POST' });
}

export function endAgreement(id: number, endDate: string, reason: string | null) {
  return apiFetch<{ agreement: Agreement; waivers_created: number }>(`${BASE}/${id}/end`, {
    method: 'POST',
    json: { end_date: endDate, reason },
  });
}

export function cancelAgreement(id: number, reason: string) {
  return apiFetch<Agreement>(`${BASE}/${id}/cancel`, { method: 'POST', json: { reason } });
}

/** The placeholder PDF, fetched with the access token and kept in memory (D40: a download). */
export function fetchAgreementPdf(id: number) {
  return apiFetch<Blob>(`${BASE}/${id}/print`, { responseType: 'blob' });
}

export function uploadSignedCopy(id: number, file: Blob, filename: string) {
  const body = new FormData();
  body.append('file', file, filename);
  return apiFetch<Agreement>(`${BASE}/${id}/signed-copy`, { method: 'POST', body });
}

export function fetchLedger(driverId: number, from: string, to: string) {
  const query = new URLSearchParams();
  if (from) query.set('from', from);
  if (to) query.set('to', to);
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiFetch<Ledger>(`/api/v1/drivers/${driverId}/ledger${suffix}`);
}

export function requestAdjustment(chargeId: number, amountPaise: number, reason: string) {
  return apiFetch<Adjustment>(`/api/v1/rent/charges/${chargeId}/adjustments`, {
    method: 'POST',
    json: { amount_paise: amountPaise, reason },
  });
}

export function decideAdjustment(
  id: number,
  decision: 'approve' | 'reject',
  reason: string | null,
) {
  return apiFetch<Adjustment>(`/api/v1/adjustments/${id}/decision`, {
    method: 'POST',
    json: { decision, reason },
  });
}

export function fetchPendingAdjustments() {
  return apiFetch<Adjustment[]>('/api/v1/adjustments?status=pending');
}

export function fetchRentSummary() {
  return apiFetch<RentSummary>('/api/v1/rent/summary');
}

export function fetchOverdue() {
  return apiFetch<OverdueRow[]>('/api/v1/rent/overdue');
}

export function runAccrual() {
  return apiFetch<{ charges_created: number; agreements: number }>('/api/v1/jobs/accrue', {
    method: 'POST',
  });
}
