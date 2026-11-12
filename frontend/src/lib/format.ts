/**
 * Display formatting. Money arrives from the API as integer paise and is formatted only here
 * (hard constraint 4). Rules match backend/app/core/money.py:
 *   12000050 -> "₹1,20,000.50", 12000000 -> "₹1,20,000" (no ".00" on whole amounts).
 * Dates and times are shown in the business time zone, Asia/Kolkata.
 */

export const BUSINESS_TIME_ZONE = 'Asia/Kolkata';

function groupIndian(rupees: bigint): string {
  const digits = rupees.toString();
  if (digits.length <= 3) return digits;
  let head = digits.slice(0, -3);
  const tail = digits.slice(-3);
  const groups: string[] = [];
  while (head.length > 2) {
    groups.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) groups.unshift(head);
  return [...groups, tail].join(',');
}

export function formatRupees(paise: number): string {
  if (!Number.isSafeInteger(paise)) {
    throw new RangeError('Money must be a whole number of paise.');
  }
  const negative = paise < 0;
  const abs = BigInt(Math.abs(paise));
  const rupees = abs / 100n;
  const rest = abs % 100n;
  let text = `${negative ? '-' : ''}₹${groupIndian(rupees)}`;
  if (rest !== 0n) text += `.${rest.toString().padStart(2, '0')}`;
  return text;
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

function parse(value: string): { date: Date; timeZone: string } {
  // A plain calendar date (e.g. a rent date) is not an instant: show it as-is.
  const isDateOnly = DATE_ONLY.test(value);
  const date = new Date(isDateOnly ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) {
    throw new RangeError(`Not a date: ${value}`);
  }
  return { date, timeZone: isDateOnly ? 'UTC' : BUSINESS_TIME_ZONE };
}

function parts(date: Date, timeZone: string, withTime: boolean): Record<string, string> {
  const formatter = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' } : {}),
  });
  const result: Record<string, string> = {};
  for (const part of formatter.formatToParts(date)) result[part.type] = part.value;
  return result;
}

/** "13 Nov 2026" in IST for an instant; unchanged for a plain YYYY-MM-DD date. */
export function formatDate(value: string): string {
  const { date, timeZone } = parse(value);
  const p = parts(date, timeZone, false);
  return `${p.day} ${p.month} ${p.year}`;
}

/** "2 Nov 2026, 10:00" in IST, 24-hour clock. */
export function formatDateTime(value: string): string {
  const { date } = parse(value);
  const p = parts(date, BUSINESS_TIME_ZONE, true);
  return `${p.day} ${p.month} ${p.year}, ${p.hour}:${p.minute}`;
}
