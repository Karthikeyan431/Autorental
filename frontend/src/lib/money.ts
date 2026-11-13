/**
 * Rupee text from a form <-> integer paise (hard constraint 4: never floats for money).
 * "2000" -> 200000, "2000.5" -> 200050, "2000.05" -> 200005. Anything else -> null.
 */

const RUPEES = /^(\d{1,13})(?:\.(\d{1,2}))?$/;

export function parseRupeesToPaise(text: string): number | null {
  const match = RUPEES.exec(text.trim().replaceAll(',', ''));
  if (!match) return null;
  const rupees = BigInt(match[1] ?? '0');
  const paise = BigInt((match[2] ?? '').padEnd(2, '0'));
  const total = rupees * 100n + paise;
  return total <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(total) : null;
}

/** For an input's value: 200000 -> "2000", 200050 -> "2000.50". No grouping, no symbol. */
export function paiseToRupeesInput(paise: number): string {
  if (!Number.isSafeInteger(paise) || paise < 0) {
    throw new RangeError('Money must be a non-negative whole number of paise.');
  }
  const rupees = Math.trunc(paise / 100);
  const rest = paise % 100;
  return rest === 0 ? String(rupees) : `${rupees}.${String(rest).padStart(2, '0')}`;
}
