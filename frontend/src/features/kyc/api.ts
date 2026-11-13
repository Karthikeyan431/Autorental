/** Consent, KYC and eligibility endpoints (docs/api.md "Consents", "KYC"). */

import { apiFetch } from '../../lib/api';
import type { KycStatus, UserRef } from '../drivers/api';
import type { PageOf } from '../staff/api';

export type CheckType = 'identity' | 'licence';
/** `uidai_qr` is never offered (D48); the server lists what a new attempt may use. */
export type KycMethod = 'manual' | 'parivahan_lookup' | 'uidai_app_attested' | 'uidai_qr' | 'demo';
export type IdDocumentType = 'masked_aadhaar' | 'voter_id' | 'passport';

export type DocumentMeta = {
  id: number;
  owner_type: string;
  owner_id: number;
  doc_type: string;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string;
  content_url: string;
};

export type ChecklistItem = { key: string; label: string; required: boolean };

/** The date or year of birth and gender are never sent; `masked_fields` names those set (D45). */
export type IdentityDetails = {
  document_type: IdDocumentType;
  id_last4: string;
  name_on_document: string | null;
  masked_fields: string[];
};

/** The licence number shows its last 4 only; the date of birth is never sent (D45). */
export type LicenceDetails = {
  licence_number_masked: string;
  name_on_licence: string | null;
  masked_fields: string[];
  issue_date: string | null;
  valid_until_non_transport: string | null;
  valid_until_transport: string | null;
  valid_until: string | null;
  vehicle_classes: string[];
  issuing_authority: string | null;
  /** Parivahan lookup record only. */
  lookup_status_text: string | null;
  looked_up_at: string | null;
};

export type KycEvent = {
  id: number;
  from_status: string | null;
  to_status: string;
  actor: UserRef | null;
  at: string;
  reason: string | null;
};

export type Attempt = {
  id: number;
  driver_id: number;
  check_type: CheckType;
  attempt_no: number;
  method: KycMethod;
  /** Honest wording, e.g. "Checked by staff with the UIDAI app" (never "Verified by system"). */
  method_label: string;
  status: KycStatus;
  is_current: boolean;
  is_simulated: boolean;
  /** Method results that are not personal data, e.g. uidai_app_signature_valid. */
  evidence: Record<string, unknown>;
  submitted_at: string | null;
  reviewed_by: UserRef | null;
  reviewed_at: string | null;
  decision_reason: string | null;
  review_checklist: Record<string, boolean> | null;
  reopened_from_id: number | null;
  created_by: UserRef | null;
  created_at: string;
  identity_details: IdentityDetails | null;
  licence_details: LicenceDetails | null;
  documents: DocumentMeta[];
  events: KycEvent[];
  checklist: ChecklistItem[];
  required_documents: string[];
};

export type Consent = {
  id: number;
  purpose: string;
  notice_version: string;
  method: string;
  captured_by: UserRef;
  captured_at: string;
  withdrawn_at: string | null;
};

export type DriverKyc = {
  driver_id: number;
  identity: Attempt | null;
  licence: Attempt | null;
  history: Attempt[];
  consents: Consent[];
  has_kyc_consent: boolean;
  accepted_id_types: IdDocumentType[];
  available_methods: Record<CheckType, KycMethod[]>;
  can_reveal: boolean;
  can_capture: boolean;
  can_decide: boolean;
  can_view_documents: boolean;
};

export type IdentityInput = {
  document_type: IdDocumentType;
  id_last4: string;
  name_on_document: string;
  /** null keeps the saved value (N17). */
  dob_or_yob: string | null;
};

export type LicenceInput = {
  /** null keeps the saved value (N17). */
  licence_number: string | null;
  name_on_licence: string;
  date_of_birth: string | null;
  issue_date: string | null;
  valid_until_non_transport: string | null;
  valid_until_transport: string | null;
  vehicle_classes: string[];
  issuing_authority: string | null;
};

export type ParivahanLookupInput = LicenceInput & {
  lookup_status_text: string;
  /** ISO date-time of the lookup; never in the future. */
  looked_up_at: string;
};

export type AttestationInput = {
  name_on_document: string;
  /** null keeps the saved value (N17). */
  dob_or_yob: string | null;
  id_last4: string;
  signature_valid: boolean;
};

/** The official licence status page. Staff open it themselves; the server never calls it. */
export const PARIVAHAN_DL_STATUS_URL = 'https://parivahan.gov.in/rcdlstatus/?pur_cd=101';

export type Decision = 'approve' | 'reject' | 'resubmit';

export type Bucket = 'pending' | 'under_review' | 'resubmission' | 'rejected' | 'expiring';

export type QueueItem = {
  driver: { id: number; code: string; full_name: string; managed_by: UserRef };
  check_type: CheckType;
  bucket: Bucket;
  attempt_id: number | null;
  attempt_no: number | null;
  status: KycStatus | null;
  submitted_at: string | null;
  licence_valid_until: string | null;
};

export type QueueCounts = Record<Bucket, number>;

export type Eligibility = {
  driver_id: number;
  on_date: string;
  ok: boolean;
  reasons: string[];
  messages: string[];
  licence_valid_until: string | null;
};

/** The notice version staff read to the driver (shown on the consent step). */
export const CONSENT_NOTICE_VERSION = 'kyc-notice-v1';

export function fetchDriverKyc(driverId: number) {
  return apiFetch<DriverKyc>(`/api/v1/drivers/${driverId}/kyc`);
}

export function recordConsent(driverId: number, method: 'in_person_signed' | 'in_person_checkbox') {
  return apiFetch<Consent>(`/api/v1/drivers/${driverId}/consents`, {
    method: 'POST',
    json: { purpose: 'kyc', notice_version: CONSENT_NOTICE_VERSION, method },
  });
}

export function startAttempt(driverId: number, checkType: CheckType, method: KycMethod) {
  return apiFetch<Attempt>(`/api/v1/drivers/${driverId}/kyc/${checkType}/attempts`, {
    method: 'POST',
    json: { method },
  });
}

export function fetchAttempt(attemptId: number) {
  return apiFetch<Attempt>(`/api/v1/kyc/attempts/${attemptId}`);
}

export function saveIdentity(attemptId: number, input: IdentityInput) {
  return apiFetch<Attempt>(`/api/v1/kyc/attempts/${attemptId}/identity-details`, {
    method: 'PUT',
    json: input,
  });
}

export function saveLicence(attemptId: number, input: LicenceInput) {
  return apiFetch<Attempt>(`/api/v1/kyc/attempts/${attemptId}/licence-details`, {
    method: 'PUT',
    json: input,
  });
}

export function saveParivahanLookup(attemptId: number, input: ParivahanLookupInput) {
  return apiFetch<Attempt>(`/api/v1/kyc/attempts/${attemptId}/parivahan-lookup`, {
    method: 'POST',
    json: input,
  });
}

export function saveAttestation(attemptId: number, input: AttestationInput) {
  return apiFetch<Attempt>(`/api/v1/kyc/attempts/${attemptId}/uidai-app-attestation`, {
    method: 'POST',
    json: input,
  });
}

export function uploadAttemptDocument(
  attemptId: number,
  docType: string,
  file: Blob,
  name: string,
) {
  const body = new FormData();
  body.append('doc_type', docType);
  body.append('file', file, name);
  return apiFetch<DocumentMeta>(`/api/v1/kyc/attempts/${attemptId}/documents`, {
    method: 'POST',
    body,
  });
}

export function submitAttempt(attemptId: number) {
  return apiFetch<Attempt>(`/api/v1/kyc/attempts/${attemptId}/submit`, { method: 'POST' });
}

export function decideAttempt(
  attemptId: number,
  decision: Decision,
  checklist: Record<string, boolean>,
  reason: string | null,
) {
  return apiFetch<Attempt>(`/api/v1/kyc/attempts/${attemptId}/decision`, {
    method: 'POST',
    json: { decision, checklist, reason },
  });
}

export function reopenAttempt(attemptId: number, reason: string) {
  return apiFetch<Attempt>(`/api/v1/kyc/attempts/${attemptId}/reopen`, {
    method: 'POST',
    json: { reason },
  });
}

export function fetchQueue(bucket: Bucket, page: number, search: string) {
  const query = new URLSearchParams({ bucket, page: String(page), page_size: '20' });
  if (search.trim()) query.set('search', search.trim());
  return apiFetch<PageOf<QueueItem>>(`/api/v1/kyc/queue?${query.toString()}`);
}

export function fetchQueueCounts() {
  return apiFetch<QueueCounts>('/api/v1/kyc/queue/counts');
}

export function fetchEligibility(driverId: number) {
  return apiFetch<Eligibility>(`/api/v1/drivers/${driverId}/eligibility`);
}
