/**
 * Weekdays are ISO everywhere (settings.weekly_pay_day, API, UI): 1 = Monday ... 7 = Sunday.
 * JavaScript's Date.getDay() counts Sunday as 0, so it is banned by ESLint; use isoWeekday().
 */
import { BUSINESS_TIME_ZONE } from './format';
import { strings } from './strings';

export type IsoWeekday = 1 | 2 | 3 | 4 | 5 | 6 | 7;

const SHORT_NAME_TO_ISO: Record<string, IsoWeekday> = {
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
  Sun: 7,
};

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * ISO weekday for an instant (in the business time zone) or a plain YYYY-MM-DD calendar date.
 */
export function isoWeekday(
  value: Date | string,
  timeZone: string = BUSINESS_TIME_ZONE,
): IsoWeekday {
  const isDateOnly = typeof value === 'string' && DATE_ONLY.test(value);
  const date =
    typeof value === 'string' ? new Date(isDateOnly ? `${value}T00:00:00Z` : value) : value;
  if (Number.isNaN(date.getTime())) throw new RangeError(`Not a date: ${String(value)}`);
  const name = new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    timeZone: isDateOnly ? 'UTC' : timeZone,
  }).format(date);
  const iso = SHORT_NAME_TO_ISO[name];
  if (!iso) throw new RangeError(`Unexpected weekday name: ${name}`);
  return iso;
}

/** Options for a weekday picker, valued 1 (Monday) to 7 (Sunday). */
export const ISO_WEEKDAY_OPTIONS = strings.weekdays.map((label, index) => ({
  value: String(index + 1),
  label,
}));
