import { ApiError } from './api';
import { strings } from './strings';

/** The server's message for a refused action, or a generic one. Never includes request data. */
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : strings.common.somethingWentWrong;
}
