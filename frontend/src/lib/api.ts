/**
 * API client. Every call sends an X-Request-ID; every failure becomes an ApiError carrying the
 * stable error code and request id from the backend's error envelope (docs/api.md).
 */

export type ErrorDetails = Record<string, unknown>;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: ErrorDetails;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null,
    details: ErrorDetails = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = details;
  }
}

type Envelope = {
  error: { code: string; message: string; details?: ErrorDetails; request_id?: string | null };
};

function isEnvelope(value: unknown): value is Envelope {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as { code?: unknown }).code === 'string' &&
    typeof (error as { message?: unknown }).message === 'string'
  );
}

export function newRequestId(): string {
  return crypto.randomUUID().replaceAll('-', '');
}

export type ApiRequestInit = Omit<RequestInit, 'body'> & { json?: unknown; body?: BodyInit };

export async function apiFetch<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const { json, headers: initHeaders, ...rest } = init;
  const headers = new Headers(initHeaders);
  const requestId = newRequestId();
  headers.set('X-Request-ID', requestId);
  headers.set('Accept', 'application/json');

  let body = rest.body;
  if (json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(json);
  }

  let response: Response;
  try {
    response = await fetch(path, { ...rest, body, headers, credentials: 'same-origin' });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server.', requestId);
  }

  const responseRequestId = response.headers.get('X-Request-ID') ?? requestId;
  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = undefined;
    }
  }

  if (!response.ok) {
    if (isEnvelope(data)) {
      throw new ApiError(
        response.status,
        data.error.code,
        data.error.message,
        data.error.request_id ?? responseRequestId,
        data.error.details ?? {},
      );
    }
    throw new ApiError(
      response.status,
      `HTTP_${response.status}`,
      'The server returned an error.',
      responseRequestId,
    );
  }
  return data as T;
}
