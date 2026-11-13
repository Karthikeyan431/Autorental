import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from '../../app/App';
import { InsecureContextBanner } from '../../components/InsecureContextBanner';
import { setAccessToken } from '../../lib/session';
import { apiError, callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { staffUser } from '../../test/users';

/**
 * Sign-in over plain http on the LAN (not a secure context): no crypto.randomUUID, no
 * navigator.locks. It must still work, explain itself with a banner, and never show a bare
 * "Something went wrong".
 */

const realCrypto = globalThis.crypto;

function makeInsecure() {
  vi.stubGlobal('crypto', { getRandomValues: realCrypto.getRandomValues.bind(realCrypto) });
  vi.stubGlobal('navigator', { ...navigator, locks: undefined });
  vi.stubGlobal('isSecureContext', false);
  Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true });
}

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
  setAccessToken(null);
  window.history.replaceState(null, '', '/');
});

const refreshRefused = apiError(401, 'REFRESH_INVALID', 'Please sign in again.');

async function fillPassword() {
  await userEvent.type(await screen.findByLabelText('Mobile number or email'), '9000000002');
  await userEvent.type(screen.getByLabelText('Password'), 'Staff-test-pass-0001');
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('Sign in without a secure context', () => {
  it('signs in with no crypto.randomUUID and no navigator.locks', async () => {
    makeInsecure();
    expect(globalThis.crypto.randomUUID).toBeUndefined();
    expect(navigator.locks).toBeUndefined();
    const fetchMock = mockApi({
      'POST /api/v1/auth/refresh': refreshRefused,
      'POST /api/v1/auth/login': {
        body: {
          status: 'ok',
          access_token: 'access-1',
          token_type: 'bearer',
          expires_in: 900,
          user: staffUser,
        },
      },
    });
    renderApp('/sign-in', { user: null });
    await fillPassword();

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Staff dashboard' }),
    ).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/v1/auth/login') as [
      string,
      RequestInit,
    ];
    expect(new Headers(init.headers).get('X-Request-ID')).toMatch(/^[0-9a-f]{32}$/);
  });

  it('shows the "Open this app over HTTPS" banner on the sign-in page', async () => {
    makeInsecure();
    mockApi({ 'POST /api/v1/auth/refresh': refreshRefused });
    window.history.replaceState(null, '', '/sign-in');
    render(<App />);

    expect(await screen.findByText('Open this app over HTTPS')).toBeInTheDocument();
    expect(await screen.findByLabelText('Mobile number or email')).toBeInTheDocument();
  });

  it('shows no banner in a secure context', () => {
    render(<InsecureContextBanner insecure={false} />);
    expect(screen.queryByText('Open this app over HTTPS')).not.toBeInTheDocument();
  });
});

describe('Sign-in errors', () => {
  it('a 401 from login does not trigger the silent refresh', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/refresh': refreshRefused,
      'POST /api/v1/auth/login': apiError(
        401,
        'INVALID_CREDENTIALS',
        'The mobile number, email or password is not correct.',
      ),
    });
    renderApp('/sign-in', { user: null });
    await screen.findByLabelText('Mobile number or email');
    const refreshesBefore = callsTo(fetchMock, 'POST', '/api/v1/auth/refresh').length;
    // A stale access token must not turn the refusal into a refresh attempt.
    setAccessToken('stale-access-token');
    await fillPassword();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The mobile number, email or password is not correct.',
    );
    expect(callsTo(fetchMock, 'POST', '/api/v1/auth/refresh')).toHaveLength(refreshesBefore);
    expect(callsTo(fetchMock, 'POST', '/api/v1/auth/login')).toHaveLength(1);
  });

  it("shows the server's message for 429", async () => {
    mockApi({
      'POST /api/v1/auth/refresh': refreshRefused,
      'POST /api/v1/auth/login': apiError(429, 'RATE_LIMITED', 'Too many attempts from here.'),
    });
    renderApp('/sign-in', { user: null });
    await fillPassword();
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts from here.');
  });

  it('shows "Something went wrong (ref: <request id>)" for an unexpected server error', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    mockApi({
      'POST /api/v1/auth/refresh': refreshRefused,
      'POST /api/v1/auth/login': apiError(500, 'INTERNAL_ERROR', 'Something went wrong.'),
    });
    renderApp('/sign-in', { user: null });
    await fillPassword();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Something went wrong (ref: testrequest01).',
    );
    expect(consoleError).toHaveBeenCalled();
  });

  it('gives a client-side exception a short ref and logs it to the console', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const fetchMock = mockApi({ 'POST /api/v1/auth/refresh': refreshRefused });
    renderApp('/sign-in', { user: null });
    await screen.findByLabelText('Mobile number or email');
    // A bug in the page (here: a response body that cannot be read) is not an ApiError.
    fetchMock.mockImplementation(
      async () =>
        ({
          ok: false,
          status: 500,
          headers: new Headers(),
          text: () => Promise.reject(new TypeError('body stream already read')),
        }) as unknown as Response,
    );
    await fillPassword();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/^Something went wrong \(ref: [0-9a-f]{8}\)\.$/);
    const ref = /ref: ([0-9a-f]{8})/.exec(alert.textContent ?? '')?.[1];
    expect(consoleError).toHaveBeenCalledWith(
      `[ARMS] Unexpected error (ref: ${ref})`,
      expect.any(TypeError),
    );
  });
});
