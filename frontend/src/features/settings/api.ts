import { apiFetch } from '../../lib/api';
import type { PageOf } from '../staff/api';

export type SettingsValues = {
  rent_due_time: string; // "HH:MM:SS"
  due_day_offset: number;
  licence_alert_days: number;
  vehicle_alert_days: number;
  permitted_licence_classes: string[];
  accepted_id_types: ('masked_aadhaar' | 'voter_id' | 'passport')[];
  advance_adjustments_enabled: boolean;
  refunds_enabled: boolean;
  staff_limit: number;
  reveal_limit_per_hour: number;
  /** N21: how many days before today an agreement may start (default 7). */
  max_backdate_days: number;
  business_name: string | null;
  business_address: string | null;
  business_upi_id: string | null;
  upi_payee_name: string | null;
  whatsapp_template: string;
  pay_request_time: string;
  weekly_pay_day: number; // ISO weekday, 1 = Monday
  escalation_suggest_after_days: number;
  weekly_mdr_warning_paise: number;
};

export type SettingsVersion = SettingsValues & {
  id: number;
  effective_from: string;
  created_at: string;
  created_by: number | null;
  created_by_name: string | null;
};

export function fetchCurrentSettings() {
  return apiFetch<SettingsVersion | null>('/api/v1/settings/current');
}

export function fetchSettingsVersions(page: number) {
  return apiFetch<PageOf<SettingsVersion>>(`/api/v1/settings/versions?page=${page}&page_size=10`);
}

export function saveSettings(changes: Partial<SettingsValues> & { reason?: string | null }) {
  return apiFetch<SettingsVersion>('/api/v1/settings', { method: 'POST', json: changes });
}
