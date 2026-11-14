/**
 * Calendar dates (YYYY-MM-DD) in the business time zone, Asia/Kolkata. Rent dates, agreement
 * start and return dates are plain calendar dates; "today" is the date in Kolkata, never the
 * browser's own zone or UTC.
 */
import { BUSINESS_TIME_ZONE } from './format';

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Today's date in Asia/Kolkata as YYYY-MM-DD (en-CA formats dates that way). */
export function businessToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: BUSINESS_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(now);
}

/** `value` plus `days` calendar days (negative to go back), as YYYY-MM-DD. */
export function addDays(value: string, days: number): string {
  const match = DATE_ONLY.exec(value);
  if (!match) throw new RangeError(`Not a date: ${value}`);
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
