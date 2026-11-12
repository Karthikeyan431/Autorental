import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiFetch } from './api';

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiFetch', () => {
  it('returns parsed JSON and sends a request id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: 'ok' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiFetch('/api/v1/health')).resolves.toEqual({ status: 'ok' });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/health');
    const headers = new Headers(init.headers);
    expect(headers.get('X-Request-ID')).toMatch(/^[0-9a-f]{32}$/);
    expect(headers.get('Accept')).toBe('application/json');
    expect(init.credentials).toBe('same-origin');
  });

  it('turns the error envelope into an ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(409, {
          error: {
            code: 'LICENCE_EXPIRED',
            message: "The driver's licence expired on 2026-10-31.",
            details: { reasons: ['LICENCE_EXPIRED'] },
            request_id: 'abc123def456',
          },
        }),
      ),
    );

    const error = await apiFetch('/api/v1/x').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(409);
    expect(apiError.code).toBe('LICENCE_EXPIRED');
    expect(apiError.message).toBe("The driver's licence expired on 2026-10-31.");
    expect(apiError.details).toEqual({ reasons: ['LICENCE_EXPIRED'] });
    expect(apiError.requestId).toBe('abc123def456');
  });

  it('handles an error without an envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('Bad gateway', { status: 502, headers: { 'X-Request-ID': 'fromheader1' } }),
        ),
    );
    const error = (await apiFetch('/api/v1/x').catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.code).toBe('HTTP_502');
    expect(error.requestId).toBe('fromheader1');
  });

  it('reports a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const error = (await apiFetch('/api/v1/x').catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.code).toBe('NETWORK_ERROR');
  });

  it('sends JSON bodies with the right content type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal('fetch', fetchMock);
    await apiFetch('/api/v1/x', { method: 'POST', json: { a: 1 } });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"a":1}');
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json');
  });

  it('returns undefined for 204 No Content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(apiFetch('/api/v1/x')).resolves.toBeUndefined();
  });
});
