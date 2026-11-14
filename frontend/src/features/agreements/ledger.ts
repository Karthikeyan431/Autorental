/** How a ledger day is labelled (Week 5: Paid, Part paid, Unpaid, Overdue; a waived day too). */
import { strings } from '../../lib/strings';
import type { LedgerRow } from './api';

const t = strings.ledger;

export type DayTone = 'ok' | 'warn' | 'bad' | 'muted';

export function dayLabel(row: Pick<LedgerRow, 'status' | 'is_overdue'>): string {
  const base = t.statuses[row.status] ?? row.status;
  return row.is_overdue ? `${base}, ${t.overdue.toLowerCase()}` : base;
}

export function dayTone(row: Pick<LedgerRow, 'status' | 'is_overdue'>): DayTone {
  if (row.is_overdue) return 'bad';
  if (row.status === 'paid') return 'ok';
  if (row.status === 'waived') return 'muted';
  return 'warn';
}
