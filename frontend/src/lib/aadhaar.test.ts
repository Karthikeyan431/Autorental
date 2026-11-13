import { describe, expect, it } from 'vitest';

import { containsAadhaarLike } from './aadhaar';

describe('containsAadhaarLike', () => {
  it.each(['123412341234', '1234 1234 1234', '1234-1234-1234', 'Name 1234 5678 9012 end'])(
    'refuses %s',
    (text) => {
      expect(containsAadhaarLike(text)).toBe(true);
    },
  );

  it.each(['0001', 'Test Driver 001', '1990-01-01', '9000000001', '+91 90000 00001', '1234 5678'])(
    'accepts %s',
    (text) => {
      expect(containsAadhaarLike(text)).toBe(false);
    },
  );
});
