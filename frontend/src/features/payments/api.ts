/** Pay request, payment, reversal and advance endpoints (docs/api.md). Money is integer paise. */

import { apiFetch } from '../../lib/api';
import type { UserRef } from '../drivers/api';
import type { PageOf } from '../staff/api';

export type PayRequestStatus = 'open' | 'paid' | 'superseded' | 'cancelled';

export type PayRequest = {
  id: number;
  driver: { id: number; code: string; full_name: string };
  managed_by: UserRef;
  agreement_id: number;
  period_start: string;
  period_end: string;
  amount_paise: number;
  reference_code: string;
  status: PayRequestStatus;
  send_count: number;
  sent_at: string | null;
  sent_by: UserRef | null;
  upi_link: string;
  whatsapp_url: string;
  mdr_warning: boolean;
  awaiting_approval_paise: number;
  created_at: string;
};

export type PaymentStatus = 'awaiting_approval' | 'approved' | 'rejected' | 'reversed';
export type PaymentMethod = 'upi' | 'cash';
export type PaymentPurpose = 'rent' | 'advance_deposit';

export type Allocation = {
  id: number;
  rent_charge_id: number;
  rent_date: string;
  amount_paise: number;
  confirmed_by: UserRef;
  confirmed_at: string;
  reversed_at: string | null;
  reversal_reason: string | null;
};

export type Payment = {
  id: number;
  driver: { id: number; code: string; full_name: string };
  agreement_id: number | null;
  amount_paise: number;
  method: PaymentMethod;
  source: string;
  purpose: PaymentPurpose;
  reference: string | null;
  received_on: string;
  status: PaymentStatus;
  recorded_by: UserRef;
  recorded_at: string;
  approved_by: UserRef | null;
  approved_at: string | null;
  rejected_by: UserRef | null;
  rejected_at: string | null;
  rejection_reason: string | null;
  reversed_at: string | null;
  receipt_no: string | null;
  receipt_cancelled: boolean;
  pay_request_id: number | null;
  proof_document_id: number | null;
  allocated_paise: number;
  unallocated_paise: number;
  days_confirmed: boolean;
  allocations: Allocation[];
  pending_reversal_id: number | null;
  can_confirm_days: boolean;
};

export type SuggestedDay = {
  rent_charge_id: number;
  rent_date: string;
  available_paise: number;
  amount_paise: number;
};

export type Suggestion = { unallocated_paise: number; items: SuggestedDay[] };

export type AllocationItem = { rent_charge_id: number; amount_paise: number };

export type ApprovalResult = {
  payment_id: number;
  outcome: 'approved' | 'refused';
  receipt_no: string | null;
  code: string | null;
  message: string | null;
};

export type ReversalRequest = {
  id: number;
  payment_id: number | null;
  driver: { id: number; code: string; full_name: string };
  amount_paise: number;
  receipt_no: string | null;
  reason: string;
  requested_by: UserRef;
  requested_at: string;
  decision: 'approved' | 'rejected' | null;
  decided_by: UserRef | null;
  decided_at: string | null;
  decision_reason: string | null;
};

export type AdvanceTransaction = {
  id: number;
  kind: 'deposit' | 'adjustment' | 'refund' | 'reversal';
  amount_paise: number;
  status: 'pending' | 'approved' | 'rejected';
  payment_id: number | null;
  reason: string | null;
  requested_by: UserRef | null;
  approved_by: UserRef | null;
  approved_at: string | null;
  created_at: string;
  allocations: Allocation[];
};

export type Advance = {
  driver_id: number;
  balance_paise: number;
  pending_use_paise: number;
  adjustments_enabled: boolean;
  refunds_enabled: boolean;
  transactions: AdvanceTransaction[];
};

export type PaymentsSummary = {
  awaiting_count: number;
  awaiting_paise: number;
  awaiting_days_unconfirmed: number;
  pending_reversals: number;
  pending_advance: number;
  requests_today: number;
  sent_today: number;
  paid_today: number;
  unpaid_today: number;
};

export type PaymentInput = {
  driver_id: number;
  amount_paise: number;
  method: PaymentMethod;
  purpose: PaymentPurpose;
  reference: string;
  received_on: string;
  idempotency_key: string;
};

export type PaymentFilters = {
  page: number;
  status: PaymentStatus | '';
  driverId?: number;
};

// --- Pay requests -----------------------------------------------------------------------------

export function fetchPayRequests(mine: boolean) {
  return apiFetch<PayRequest[]>(`/api/v1/pay-requests${mine ? '?mine=true' : ''}`);
}

export function generatePayRequests() {
  return apiFetch<{ created: number; superseded: number; unchanged: number }>(
    '/api/v1/pay-requests/generate',
    { method: 'POST' },
  );
}

export function markSent(id: number) {
  return apiFetch<PayRequest>(`/api/v1/pay-requests/${id}/sent`, { method: 'POST' });
}

export function fetchPayRequestQr(id: number) {
  return apiFetch<Blob>(`/api/v1/pay-requests/${id}/qr.png`, { responseType: 'blob' });
}

// --- Payments ---------------------------------------------------------------------------------

export function listPayments(filters: PaymentFilters) {
  const query = new URLSearchParams({ page: String(filters.page), page_size: '20' });
  if (filters.status) query.set('status', filters.status);
  if (filters.driverId !== undefined) query.set('driver_id', String(filters.driverId));
  return apiFetch<PageOf<Payment>>(`/api/v1/payments?${query.toString()}`);
}

export function fetchPayment(id: number) {
  return apiFetch<Payment>(`/api/v1/payments/${id}`);
}

export function recordPayment(input: PaymentInput, proof: Blob, proofName: string) {
  const body = new FormData();
  body.append('driver_id', String(input.driver_id));
  body.append('amount_paise', String(input.amount_paise));
  body.append('method', input.method);
  body.append('purpose', input.purpose);
  if (input.reference.trim()) body.append('reference', input.reference.trim());
  body.append('received_on', input.received_on);
  body.append('idempotency_key', input.idempotency_key);
  body.append('proof', proof, proofName);
  return apiFetch<Payment>('/api/v1/payments', { method: 'POST', body });
}

export function fetchSuggestion(id: number) {
  return apiFetch<Suggestion>(`/api/v1/payments/${id}/suggestion`);
}

export function confirmDays(id: number, items: AllocationItem[]) {
  return apiFetch<Payment>(`/api/v1/payments/${id}/allocations`, {
    method: 'PUT',
    json: { items },
  });
}

export function applyCredit(id: number, items: AllocationItem[]) {
  return apiFetch<Payment>(`/api/v1/payments/${id}/allocations`, {
    method: 'POST',
    json: { items },
  });
}

export function approvePayments(ids: number[]) {
  return apiFetch<ApprovalResult[]>('/api/v1/payments/approve', {
    method: 'POST',
    json: { ids },
  });
}

export function rejectPayment(id: number, reason: string) {
  return apiFetch<Payment>(`/api/v1/payments/${id}/reject`, { method: 'POST', json: { reason } });
}

/** The receipt PDF, fetched with the access token (D40: a download). */
export function fetchReceiptPdf(id: number) {
  return apiFetch<Blob>(`/api/v1/payments/${id}/receipt.pdf`, { responseType: 'blob' });
}

export function fetchPaymentsSummary() {
  return apiFetch<PaymentsSummary>('/api/v1/payments/summary');
}

// --- Reversals --------------------------------------------------------------------------------

export function requestReversal(paymentId: number, reason: string) {
  return apiFetch<ReversalRequest>(`/api/v1/payments/${paymentId}/reversal-requests`, {
    method: 'POST',
    json: { reason },
  });
}

export function fetchReversalRequests() {
  return apiFetch<ReversalRequest[]>('/api/v1/reversal-requests');
}

export function decideReversal(
  id: number,
  decision: 'approved' | 'rejected',
  reason: string | null,
) {
  return apiFetch<ReversalRequest>(`/api/v1/reversal-requests/${id}/decision`, {
    method: 'POST',
    json: { decision, reason },
  });
}

// --- Advance ----------------------------------------------------------------------------------

export function fetchAdvance(driverId: number) {
  return apiFetch<Advance>(`/api/v1/drivers/${driverId}/advance`);
}

export function requestAdvanceAdjustment(
  driverId: number,
  items: AllocationItem[],
  reason: string,
) {
  return apiFetch<AdvanceTransaction>('/api/v1/advance/adjustments', {
    method: 'POST',
    json: { driver_id: driverId, items, reason },
  });
}

export function fetchPendingAdvance() {
  return apiFetch<AdvanceTransaction[]>('/api/v1/advance/pending');
}

export function decideAdvance(
  id: number,
  decision: 'approved' | 'rejected',
  reason: string | null,
) {
  return apiFetch<AdvanceTransaction>(`/api/v1/advance/${id}/decision`, {
    method: 'POST',
    json: { decision, reason },
  });
}
