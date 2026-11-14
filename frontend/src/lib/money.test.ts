import { describe, expect, it } from 'vitest';

import { paiseToRupeesInput, parseRupeesToPaise, parseSignedRupeesToPaise } from './money';

describe('parseRupeesToPaise', () => {
  it.each([
    ['2000', 200000],
    ['2000.5', 200050],
    ['2000.05', 200005],
    ['0', 0],
    ['1,20,000', 12000000],
    [' 300 ', 30000],
  ])('%s -> %i paise', (text, paise) => {
    expect(parseRupeesToPaise(text)).toBe(paise);
  });

  it.each(['', 'abc', '-5', '1.234', '1e3', '0.1.2'])('refuses %s', (text) => {
    expect(parseRupeesToPaise(text)).toBeNull();
  });

  it('never goes through floating point', () => {
    // 0.1 + 0.2 style errors cannot happen: 1.10 is exactly 110 paise.
    expect(parseRupeesToPaise('1.10')).toBe(110);
    expect(parseRupeesToPaise('19.99')).toBe(1999);
  });
});

describe('paiseToRupeesInput', () => {
  it.each([
    [200000, '2000'],
    [200050, '2000.50'],
    [5, '0.05'],
  ])('%i -> %s', (paise, text) => {
    expect(paiseToRupeesInput(paise)).toBe(text);
  });

  it('refuses fractions of a paisa', () => {
    expect(() => paiseToRupeesInput(1.5)).toThrow(RangeError);
  });
});

describe('parseSignedRupeesToPaise', () => {
  it('reads waivers and additions as whole paise', () => {
    expect(parseSignedRupeesToPaise('-300')).toBe(-30000);
    expect(parseSignedRupeesToPaise('50.5')).toBe(5050);
    expect(parseSignedRupeesToPaise('+50')).toBe(5000);
    expect(parseSignedRupeesToPaise(' -1,200.25 ')).toBe(-120025);
  });

  it('refuses zero and anything that is not money', () => {
    for (const text of ['0', '-0', '', '-', '--3', '3e2', '1.234', 'abc']) {
      expect(parseSignedRupeesToPaise(text)).toBeNull();
    }
  });
});
