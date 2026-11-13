import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { setAccessToken } from '../../lib/session';
import { apiError, callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser, staffUser } from '../../test/users';

const signedIn = (user = staffUser) => ({
  body: { status: 'ok', access_token: 'access-1', token_type: 'bearer', expires_in: 900, user },
});

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
});

async function fillPassword(login = '9000000002', password = 'Staff-test-pass-0001') {
  await userEvent.type(await screen.findByLabelText('Mobile number or email'), login);
  await userEvent.type(screen.getByLabelText('Password'), password);
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
}

describe('Sign in', () => {
  it('signs staff in and opens the staff dashboard', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
      'POST /api/v1/auth/login': signedIn(),
    });
    renderApp('/sign-in', { user: null });
    await fillPassword();

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Staff dashboard' }),
    ).toBeInTheDocument();
    const [call] = callsTo(fetchMock, 'POST', '/api/v1/auth/login');
    expect(call?.body).toEqual({ login: '9000000002', password: 'Staff-test-pass-0001' });
  });

  it('validates the form before calling the API', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
    });
    renderApp('/sign-in', { user: null });
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }));
    expect(screen.getByText('Enter your mobile number or email.')).toBeInTheDocument();
    expect(screen.getByText('Enter your password.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/auth/login')).toHaveLength(0);
  });

  it('shows the refusal from the server', async () => {
    mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
      'POST /api/v1/auth/login': apiError(
        401,
        'INVALID_CREDENTIALS',
        'The mobile number, email or password is not correct.',
      ),
    });
    renderApp('/sign-in', { user: null });
    await fillPassword();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The mobile number, email or password is not correct.',
    );
    expect(screen.getByLabelText('Password')).toHaveValue('');
  });

  it('shows the lockout message', async () => {
    mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
      'POST /api/v1/auth/login': apiError(
        429,
        'ACCOUNT_LOCKED',
        'Too many attempts. Try again in 15 minutes.',
      ),
    });
    renderApp('/sign-in', { user: null });
    await fillPassword();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Too many attempts. Try again in 15 minutes.',
    );
  });

  it('asks the owner for the TOTP code before signing in', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
      'POST /api/v1/auth/login': {
        body: { status: 'totp_required', challenge_token: 'challenge-1' },
      },
      'POST /api/v1/auth/totp': signedIn(ownerUser),
    });
    renderApp('/sign-in', { user: null });
    await fillPassword('9000000001', 'Owner-test-pass-0001');

    const code = await screen.findByLabelText('6-digit code');
    await userEvent.type(code, '12345');
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(screen.getByText('Enter the 6 digits from the app.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/auth/totp')).toHaveLength(0);

    await userEvent.type(code, '6');
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Owner dashboard' }),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/auth/totp')[0]?.body).toEqual({
      challenge_token: 'challenge-1',
      code: '123456',
    });
  });

  it('lets the owner use a recovery code instead', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
      'POST /api/v1/auth/login': {
        body: { status: 'totp_required', challenge_token: 'challenge-1' },
      },
      'POST /api/v1/auth/totp': signedIn(ownerUser),
    });
    renderApp('/sign-in', { user: null });
    await fillPassword('9000000001', 'Owner-test-pass-0001');
    await userEvent.click(
      await screen.findByRole('button', { name: 'Use a recovery code instead' }),
    );
    await userEvent.type(screen.getByLabelText('Recovery code'), 'abcde-fghjk');
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }));
    await screen.findByRole('heading', { level: 1, name: 'Owner dashboard' });
    expect(callsTo(fetchMock, 'POST', '/api/v1/auth/totp')[0]?.body).toEqual({
      challenge_token: 'challenge-1',
      recovery_code: 'abcde-fghjk',
    });
  });

  it('enrols the owner at first sign-in and requires the recovery codes to be saved', async () => {
    const codes = Array.from({ length: 10 }, (_, i) => `abcd${i}-efgh${i}`);
    mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
      'POST /api/v1/auth/login': {
        body: { status: 'totp_setup_required', challenge_token: 'challenge-setup' },
      },
      'POST /api/v1/auth/totp/setup': {
        body: {
          secret: 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP',
          otpauth_uri: 'otpauth://totp/Auto%20Rental%20Manager:Owner?secret=X',
          qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        },
      },
      'POST /api/v1/auth/totp/confirm': {
        body: { ...signedIn(ownerUser).body, recovery_codes: codes },
      },
    });
    renderApp('/sign-in', { user: null });
    await fillPassword('9000000001', 'Owner-test-pass-0001');

    expect(
      await screen.findByAltText('QR code to add Auto Rental Manager to your authenticator app'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('totp-secret')).toHaveTextContent('JBSW Y3DP');
    await userEvent.type(screen.getByLabelText('6-digit code'), '654321');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(await screen.findByText('Save your recovery codes')).toBeInTheDocument();
    for (const code of codes) expect(screen.getByText(code)).toBeInTheDocument();
    const next = screen.getByRole('button', { name: 'Continue' });
    expect(next).toBeDisabled();
    await userEvent.click(screen.getByLabelText('I have saved these codes'));
    expect(next).toBeEnabled();
    await userEvent.click(next);
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Owner dashboard' }),
    ).toBeInTheDocument();
  });

  it('goes back to the password step when the challenge expires', async () => {
    mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
      'POST /api/v1/auth/login': {
        body: { status: 'totp_required', challenge_token: 'challenge-1' },
      },
      'POST /api/v1/auth/totp': apiError(
        401,
        'CHALLENGE_INVALID',
        'This sign-in step has expired. Please sign in again.',
      ),
    });
    renderApp('/sign-in', { user: null });
    await fillPassword('9000000001', 'Owner-test-pass-0001');
    await userEvent.type(await screen.findByLabelText('6-digit code'), '123456');
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }));
    expect(
      await screen.findByText('This sign-in step has expired. Please sign in again.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Mobile number or email')).toBeInTheDocument();
  });
});

describe('Session restore', () => {
  it('stays signed in after a reload by refreshing from the cookie', async () => {
    document.cookie = 'arms_csrf=csrf-from-cookie; path=/';
    const fetchMock = mockApi({ 'POST /api/v1/auth/refresh': signedIn(ownerUser) });
    renderApp('/', { user: null });
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Owner dashboard' }),
    ).toBeInTheDocument();
    const [call] = callsTo(fetchMock, 'POST', '/api/v1/auth/refresh');
    expect(call?.headers.get('X-CSRF-Token')).toBe('csrf-from-cookie');
    expect(callsTo(fetchMock, 'POST', '/api/v1/auth/refresh')).toHaveLength(1);
    document.cookie = 'arms_csrf=; path=/; max-age=0';
  });

  it('sends a signed-out visitor to the sign-in page', async () => {
    mockApi({
      'POST /api/v1/auth/refresh': apiError(401, 'REFRESH_INVALID', 'Please sign in again.'),
    });
    renderApp('/staff', { user: null });
    expect(await screen.findByRole('heading', { level: 1, name: 'Sign in' })).toBeInTheDocument();
  });

  it('forces a password change when required', async () => {
    mockApi({});
    renderApp('/', { user: { ...staffUser, must_change_password: true } });
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Change your password' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText('You signed in with a temporary password. Choose a new one to continue.'),
    ).toBeInTheDocument();
  });

  it('changes the password and continues', async () => {
    const fetchMock = mockApi({ 'POST /api/v1/auth/change-password': { status: 204 } });
    renderApp('/change-password', { user: { ...staffUser, must_change_password: true } });
    await userEvent.type(await screen.findByLabelText('Current password'), 'Temp-pass-0001x');
    await userEvent.type(screen.getByLabelText('New password'), 'Brand-new-pass-0002');
    await userEvent.type(screen.getByLabelText('New password again'), 'Brand-new-pass-000X');
    await userEvent.click(screen.getByRole('button', { name: 'Save password' }));
    expect(screen.getByText('The two new passwords do not match.')).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText('New password again'));
    await userEvent.type(screen.getByLabelText('New password again'), 'Brand-new-pass-0002');
    await userEvent.click(screen.getByRole('button', { name: 'Save password' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Staff dashboard' }),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/auth/change-password')[0]?.body).toEqual({
      current_password: 'Temp-pass-0001x',
      new_password: 'Brand-new-pass-0002',
    });
  });
});
