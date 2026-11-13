import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiFetch } from './api';
import { setAccessToken, setRefreshHandler, setSessionExpiredHandler } from './session';

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

describe('apiFetch with a session', () => {
  afterEach(() => {
    setAccessToken(null);
    setRefreshHandler(null);
    setSessionExpiredHandler(null);
  });

  it('sends the access token as a Bearer header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('token-1');
    await apiFetch('/api/v1/settings/current');
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer token-1');
  });

  it('refreshes once on 401 and retries with the new token', async () => {
    const unauthenticated = { error: { code: 'UNAUTHENTICATED', message: 'Please sign in.' } };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, unauthenticated))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('old-token');
    const refresh = vi.fn(async () => {
      setAccessToken('new-token');
      return true;
    });
    setRefreshHandler(refresh);

    await expect(apiFetch('/api/v1/users')).resolves.toEqual({ ok: true });
    expect(refresh).toHaveBeenCalledTimes(1);
    const [, retry] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(new Headers(retry.headers).get('Authorization')).toBe('Bearer new-token');
  });

  it('ends the session when the refresh fails', async () => {
    const unauthenticated = { error: { code: 'UNAUTHENTICATED', message: 'Please sign in.' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, unauthenticated)));
    setAccessToken('old-token');
    setRefreshHandler(async () => false);
    const expired = vi.fn();
    setSessionExpiredHandler(expired);

    const error = (await apiFetch('/api/v1/users').catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(401);
    expect(expired).toHaveBeenCalledTimes(1);
  });

  it('never refreshes for the auth endpoints themselves', async () => {
    const refusal = { error: { code: 'INVALID_CREDENTIALS', message: 'Not correct.' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, refusal)));
    setAccessToken('old-token');
    const refresh = vi.fn(async () => true);
    setRefreshHandler(refresh);
    await apiFetch('/api/v1/auth/login', { method: 'POST' }).catch(() => undefined);
    expect(refresh).not.toHaveBeenCalled();
  });
});
