import { describe, expect, it } from 'vitest';

import { addDays, businessToday } from './dates';

describe('businessToday', () => {
  it('is the date in Kolkata, not UTC', () => {
    // 19:00 UTC on 9 Nov is 00:30 IST on 10 Nov.
    expect(businessToday(new Date('2026-11-09T19:00:00Z'))).toBe('2026-11-10');
    expect(businessToday(new Date('2026-11-09T18:29:00Z'))).toBe('2026-11-09');
  });
});

describe('addDays', () => {
  it('moves across months and leap days', () => {
    expect(addDays('2026-11-13', 1)).toBe('2026-11-14');
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31');
    expect(addDays('2028-02-28', 1)).toBe('2028-02-29');
    expect(addDays('2027-02-28', 1)).toBe('2027-03-01');
  });

  it('refuses anything that is not a calendar date', () => {
    expect(() => addDays('13/11/2026', 1)).toThrow(RangeError);
  });
});
