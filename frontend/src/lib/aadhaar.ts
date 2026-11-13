/**
 * Hard constraint 5: a full Aadhaar number is never stored. Every identity and free-text field
 * refuses 12 digits in a row (optionally grouped 4-4-4 by spaces or dashes). The backend checks
 * the same rule (app/core/identifiers.py); this gives staff the message before they submit.
 */

const AADHAAR_LIKE = /(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)/;

export function containsAadhaarLike(text: string): boolean {
  return AADHAAR_LIKE.test(text);
}

export const NO_FULL_NUMBER_MESSAGE =
  'A full 12-digit number is not allowed here. Never record a full Aadhaar number.';
