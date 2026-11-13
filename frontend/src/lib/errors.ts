import { ApiError, newRequestId } from './api';
import { strings } from './strings';

/** Server answers whose message is meant for the user (any envelope code except a crash). */
function isExpected(error: ApiError): boolean {
  return !error.code.startsWith('HTTP_') && error.code !== 'INTERNAL_ERROR';
}

/**
 * The text to show for a failed action. Never includes request data.
 *
 * - A refusal the server explained (wrong password, 429 too many attempts, a business rule,
 *   no connection): the server's own message.
 * - Anything unexpected (a 500, a response that is not our envelope, a bug in this page):
 *   "Something went wrong (ref: …)". The ref is the request id when there is one, otherwise a
 *   short id made here; the error is logged to the browser console with the same ref.
 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError && isExpected(error)) return error.message;
  const ref =
    error instanceof ApiError && error.requestId ? error.requestId : newRequestId().slice(0, 8);
  console.error(`[ARMS] Unexpected error (ref: ${ref})`, error);
  return strings.common.somethingWentWrongRef(ref);
}
