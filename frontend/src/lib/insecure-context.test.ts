import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, apiFetch, newRequestId } from './api';
import { errorMessage } from './errors';
import { createRefreshCoordinator } from './refresh-coordinator';
import { isInsecureContext } from './secure-context';
import { setAccessToken, setRefreshHandler } from './session';

/**
 * Plain http on the LAN is not a secure context: browsers remove crypto.randomUUID and
 * navigator.locks there. The app must keep working without them.
 */

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const realCrypto = globalThis.crypto;

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
  setRefreshHandler(null);
});

describe('request ids without crypto.randomUUID', () => {
  it('uses getRandomValues when randomUUID is missing', () => {
    const getRandomValues = vi.fn((array: Uint8Array<ArrayBuffer>) =>
      realCrypto.getRandomValues(array),
    );
    const id = newRequestId({ getRandomValues } as unknown as Partial<Crypto>);
    expect(id).toMatch(/^[0-9a-f]{32}$/);
    expect(getRandomValues).toHaveBeenCalledOnce();
  });

  it('still makes an id with no crypto at all', () => {
    expect(newRequestId(undefined)).toMatch(/^[0-9a-f]{32}$/);
    expect(newRequestId({})).toMatch(/^[0-9a-f]{32}$/);
  });

  it('apiFetch sends a request id when the page has no randomUUID', async () => {
    vi.stubGlobal('crypto', { getRandomValues: realCrypto.getRandomValues.bind(realCrypto) });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { status: 'ok' }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiFetch('/api/v1/health')).resolves.toEqual({ status: 'ok' });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get('X-Request-ID')).toMatch(/^[0-9a-f]{32}$/);
  });
});

describe('the refresh lock without navigator.locks', () => {
  it('refreshes directly when Web Locks are missing', async () => {
    vi.stubGlobal('navigator', { ...navigator, locks: undefined });
    const callRefresh = vi.fn().mockResolvedValue('fresh');
    const coordinator = createRefreshCoordinator({
      callRefresh,
      onRemoteRefresh: () => {},
      onRemoteSignOut: () => {},
      channel: null,
    });

    await expect(coordinator.refresh()).resolves.toBe('fresh');
    expect(callRefresh).toHaveBeenCalledOnce();
    coordinator.close();
  });
});

describe('isInsecureContext', () => {
  it('is true only when the browser says the page is not secure', () => {
    expect(isInsecureContext({ isSecureContext: false } as Window)).toBe(true);
    expect(isInsecureContext({ isSecureContext: true } as Window)).toBe(false);
    expect(isInsecureContext(undefined)).toBe(false);
  });
});

describe('auth endpoints never trigger the silent refresh', () => {
  it.each([
    '/api/v1/auth/login',
    '/api/v1/auth/totp',
    '/api/v1/auth/totp/setup',
    '/api/v1/auth/totp/confirm',
    '/api/v1/auth/refresh',
  ])('a 401 from %s is returned as is', async (path) => {
    setAccessToken('stale-access-token');
    const handler = vi.fn().mockResolvedValue(true);
    setRefreshHandler(handler);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() =>
        jsonResponse(401, {
          error: { code: 'INVALID_CREDENTIALS', message: 'Not correct.', request_id: 'r1' },
        }),
      ),
    );

    // With and without auth: false, a 401 here is the answer, not an expired token.
    await expect(apiFetch(path, { method: 'POST', json: {} })).rejects.toMatchObject({
      status: 401,
      code: 'INVALID_CREDENTIALS',
    });
    await expect(apiFetch(path, { method: 'POST', json: {}, auth: false })).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(handler).not.toHaveBeenCalled();
  });
});

describe('errorMessage', () => {
  it("shows the server's message for 401, 429 and known codes", () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(errorMessage(new ApiError(401, 'INVALID_CREDENTIALS', 'Not correct.', 'r1'))).toBe(
      'Not correct.',
    );
    expect(errorMessage(new ApiError(429, 'RATE_LIMITED', 'Too many attempts.', 'r2'))).toBe(
      'Too many attempts.',
    );
    expect(errorMessage(new ApiError(423, 'ACCOUNT_LOCKED', 'Locked.', 'r3'))).toBe('Locked.');
    expect(
      errorMessage(new ApiError(0, 'NETWORK_ERROR', 'Could not reach the server.', 'r4')),
    ).toBe('Could not reach the server.');
    expect(spy).not.toHaveBeenCalled();
  });

  it('shows a ref (the request id) for unexpected server errors and logs them', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(errorMessage(new ApiError(500, 'INTERNAL_ERROR', 'Oops.', 'abc123def456'))).toBe(
      'Something went wrong (ref: abc123def456).',
    );
    expect(errorMessage(new ApiError(502, 'HTTP_502', 'The server returned an error.', 'r9'))).toBe(
      'Something went wrong (ref: r9).',
    );
    expect(spy).toHaveBeenCalledTimes(2);
    expect(String(spy.mock.calls[0]?.[0])).toContain('abc123def456');
  });

  it('gives a client-side exception a short ref and logs it to the console', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const error = new TypeError('crypto.randomUUID is not a function');
    const message = errorMessage(error);
    const ref = /^Something went wrong \(ref: ([0-9a-f]{8})\)\.$/.exec(message)?.[1];
    expect(ref).toBeDefined();
    expect(spy).toHaveBeenCalledWith(`[ARMS] Unexpected error (ref: ${ref})`, error);
  });
});
