import { describe, expect, it } from 'vitest';

import { ISO_WEEKDAY_OPTIONS, isoWeekday } from './weekday';

describe('isoWeekday (1 = Monday ... 7 = Sunday, same as the backend)', () => {
  it.each([
    ['2026-11-02', 1], // Monday
    ['2026-11-03', 2],
    ['2026-11-07', 6], // Saturday
    ['2026-11-08', 7], // Sunday: 7, never 0
    ['2028-02-29', 2], // leap day, a Tuesday
  ])('calendar date %s is weekday %i', (day, expected) => {
    expect(isoWeekday(day)).toBe(expected);
  });

  it('uses the business time zone for instants', () => {
    // 00:01 IST on Monday 9 Nov 2026 is still Sunday 8 Nov in UTC.
    expect(isoWeekday('2026-11-08T18:31:00Z')).toBe(1);
    // 23:59 IST on Sunday 8 Nov 2026.
    expect(isoWeekday(new Date('2026-11-08T18:29:00Z'))).toBe(7);
  });

  it('never returns 0 for Sunday', () => {
    const sunday = isoWeekday('2026-11-08');
    expect(sunday).not.toBe(0);
    expect(sunday).toBe(7);
  });

  it('refuses text that is not a date', () => {
    expect(() => isoWeekday('not a date')).toThrow();
  });

  it('picker options run Monday=1 to Sunday=7', () => {
    expect(ISO_WEEKDAY_OPTIONS[0]).toEqual({ value: '1', label: 'Monday' });
    expect(ISO_WEEKDAY_OPTIONS[6]).toEqual({ value: '7', label: 'Sunday' });
    expect(ISO_WEEKDAY_OPTIONS).toHaveLength(7);
  });
});
