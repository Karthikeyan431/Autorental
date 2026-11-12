import { describe, expect, it } from 'vitest';

import { formatDate, formatDateTime, formatRupees } from './format';

describe('formatRupees (paise in, Indian grouping out; same rules as the backend)', () => {
  it.each([
    [12000050, '₹1,20,000.50'],
    [12000000, '₹1,20,000'],
    [30000, '₹300'],
    [0, '₹0'],
    [1, '₹0.01'],
    [50, '₹0.50'],
    [99999, '₹999.99'],
    [100000, '₹1,000'],
    [10000000, '₹1,00,000'],
    [1000000000, '₹1,00,00,000'],
    [-30000, '-₹300'],
    [-12000050, '-₹1,20,000.50'],
  ])('%i paise -> %s', (paise, expected) => {
    expect(formatRupees(paise)).toBe(expected);
  });

  it.each([300.5, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 2])(
    'refuses %s (paise must be a safe integer)',
    (value) => {
      expect(() => formatRupees(value)).toThrow(/paise/i);
    },
  );
});

describe('dates are shown in Asia/Kolkata', () => {
  it('shows the IST calendar date for a UTC instant', () => {
    // 00:01 IST on 13 Nov 2026 is 18:31 UTC on 12 Nov.
    expect(formatDate('2026-11-12T18:31:00Z')).toBe('13 Nov 2026');
    // 23:59 IST on 12 Nov 2026 is 18:29 UTC on 12 Nov.
    expect(formatDate('2026-11-12T18:29:00Z')).toBe('12 Nov 2026');
  });

  it('shows IST date and 24-hour time', () => {
    expect(formatDateTime('2026-11-02T04:30:00Z')).toBe('2 Nov 2026, 10:00');
    expect(formatDateTime('2026-11-04T20:30:00Z')).toBe('5 Nov 2026, 02:00');
  });

  it('keeps a plain calendar date unchanged', () => {
    expect(formatDate('2026-11-05')).toBe('5 Nov 2026');
  });

  it('refuses text that is not a date', () => {
    expect(() => formatDate('not a date')).toThrow();
  });
});
