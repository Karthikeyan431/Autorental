import type { Driver } from '../features/drivers/api';
import type { Attempt, DriverKyc } from '../features/kyc/api';

/** Obviously fake driver data for tests (hard constraint 7). */

export const driver: Driver = {
  id: 7,
  code: 'D0007',
  full_name: 'Test Driver 007',
  mobile: '+919000000007',
  alt_mobile: null,
  masked_fields: ['address', 'date_of_birth'],
  can_reveal: true,
  emergency_name: null,
  emergency_mobile: null,
  photo_document_id: null,
  account_status: 'active',
  status_reason: null,
  payment_rhythm: 'daily',
  registered_at: '2026-11-10T05:00:00Z',
  created_by: { id: 2, name: 'Test Staff 001' },
  managed_by: { id: 2, name: 'Test Staff 001' },
  managed_since: '2026-11-10T05:00:00Z',
  identity_status: 'submitted',
  licence_status: null,
  can_edit: true,
  can_view_kyc: true,
};

export const identityChecklist = [
  {
    key: 'last4_only_visible',
    label: 'Only the last 4 digits of the Aadhaar number are visible',
    required: true,
  },
  {
    key: 'photo_matches_person',
    label: 'The photo matches the person in front of you',
    required: true,
  },
  {
    key: 'details_match_document',
    label: 'The typed name, date of birth and last 4 digits match the document',
    required: true,
  },
];

export const identityAttempt: Attempt = {
  id: 31,
  driver_id: 7,
  check_type: 'identity',
  attempt_no: 1,
  method: 'manual',
  method_label: 'Manual review of the documents',
  status: 'submitted',
  is_current: true,
  is_simulated: false,
  evidence: {},
  submitted_at: '2026-11-10T06:00:00Z',
  reviewed_by: null,
  reviewed_at: null,
  decision_reason: null,
  review_checklist: null,
  reopened_from_id: null,
  created_by: { id: 2, name: 'Test Staff 001' },
  created_at: '2026-11-10T05:30:00Z',
  identity_details: {
    document_type: 'masked_aadhaar',
    id_last4: '0007',
    name_on_document: 'Test Driver 007',
    masked_fields: ['id_dob_or_yob'],
  },
  licence_details: null,
  documents: [],
  events: [
    {
      id: 1,
      from_status: null,
      to_status: 'draft',
      actor: { id: 2, name: 'Test Staff 001' },
      at: '2026-11-10T05:30:00Z',
      reason: null,
    },
  ],
  checklist: identityChecklist,
  required_documents: ['id_front'],
};

export const driverKyc: DriverKyc = {
  driver_id: 7,
  identity: identityAttempt,
  licence: null,
  history: [identityAttempt],
  consents: [
    {
      id: 1,
      purpose: 'kyc',
      notice_version: 'kyc-notice-v1',
      method: 'in_person_checkbox',
      captured_by: { id: 2, name: 'Test Staff 001' },
      captured_at: '2026-11-10T05:20:00Z',
      withdrawn_at: null,
    },
  ],
  has_kyc_consent: true,
  accepted_id_types: ['masked_aadhaar'],
  available_methods: { identity: ['manual'], licence: ['manual', 'parivahan_lookup'] },
  can_reveal: true,
  can_capture: true,
  can_decide: true,
  can_view_documents: true,
};
