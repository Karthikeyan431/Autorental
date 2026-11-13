import type { User } from '../features/auth/api';

/** Obviously fake users for tests (hard constraint 7). */

export const ALL_PERMISSIONS = [
  'adjustments.decide',
  'adjustments.request',
  'advance.decide',
  'agreements.manage',
  'audit.view',
  'drivers.create',
  'drivers.edit_any',
  'drivers.edit_own',
  'drivers.reassign',
  'drivers.restrict',
  'escalations.raise',
  'escalations.work',
  'kyc.decide',
  'kyc.reopen',
  'payments.approve',
  'payments.record',
  'payments.reverse_decide',
  'payrequests.send',
  'reports.all',
  'settings.manage',
  'statements.upload',
  'users.manage',
  'vehicles.manage',
];

export const STAFF_DEFAULT_PERMISSIONS = [
  'adjustments.request',
  'agreements.manage',
  'drivers.create',
  'drivers.edit_own',
  'escalations.work',
  'kyc.decide',
  'payments.record',
  'payrequests.send',
  'vehicles.manage',
];

export const ownerUser: User = {
  id: 1,
  name: 'Test Owner',
  mobile: '+919000000001',
  email: 'owner@example.test',
  role: 'owner',
  is_active: true,
  must_change_password: false,
  totp_enabled: true,
  last_login_at: null,
  deactivated_at: null,
  created_at: '2026-11-13T00:00:00Z',
  permissions: ALL_PERMISSIONS,
};

export const staffUser: User = {
  ...ownerUser,
  id: 2,
  name: 'Test Staff 001',
  mobile: '+919000000002',
  email: null,
  role: 'staff',
  totp_enabled: false,
  permissions: STAFF_DEFAULT_PERMISSIONS,
};
