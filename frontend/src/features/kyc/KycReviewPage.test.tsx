import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { driver, driverKyc, identityAttempt } from '../../test/drivers';
import { callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser, staffUser } from '../../test/users';

afterEach(() => {
  vi.unstubAllGlobals();
});

const approved = {
  ...identityAttempt,
  status: 'approved' as const,
  reviewed_by: { id: 2, name: 'Test Staff 001' },
  reviewed_at: '2026-11-11T06:00:00Z',
};

function setup(attempt = identityAttempt, extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    'GET /api/v1/kyc/attempts/31': { body: attempt },
    'GET /api/v1/drivers/7': { body: driver },
    'GET /api/v1/drivers/7/kyc': { body: driverKyc },
    ...extra,
  });
}

describe('KYC review', () => {
  it('approves only when every required item is ticked, including the last-4 check', async () => {
    const fetchMock = setup(identityAttempt, {
      'POST /api/v1/kyc/attempts/31/decision': { body: approved },
    });
    renderApp('/kyc/attempts/31', { user: staffUser });
    const approve = await screen.findByRole('button', { name: 'Approve' });
    expect(approve).toBeDisabled();

    await userEvent.click(screen.getByRole('checkbox', { name: /photo matches the person/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: /typed name/ }));
    expect(approve).toBeDisabled(); // the last-4 item is still unticked

    await userEvent.click(
      screen.getByRole('checkbox', {
        name: 'Only the last 4 digits of the Aadhaar number are visible',
      }),
    );
    expect(approve).toBeEnabled();
    await userEvent.click(approve);

    expect(await screen.findByText('Decision saved.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/kyc/attempts/31/decision')[0]?.body).toEqual({
      decision: 'approve',
      checklist: {
        photo_matches_person: true,
        details_match_document: true,
        last4_only_visible: true,
      },
      reason: null,
    });
  });

  it('makes the difference between asking again and a final rejection clear', async () => {
    const fetchMock = setup(identityAttempt, {
      'POST /api/v1/kyc/attempts/31/decision': { body: { ...identityAttempt, status: 'rejected' } },
    });
    renderApp('/kyc/attempts/31', { user: staffUser });
    expect(
      await screen.findByRole('button', { name: 'Ask for documents again' }),
    ).toBeInTheDocument();
    const reject = screen.getByRole('button', {
      name: 'Reject (final; only the owner can reopen)',
    });

    await userEvent.click(reject);
    expect(screen.getByRole('alert')).toHaveTextContent('Give a reason.');
    expect(callsTo(fetchMock, 'POST', '/api/v1/kyc/attempts/31/decision')).toHaveLength(0);

    await userEvent.type(
      screen.getByLabelText('Reason (required to reject or ask again)'),
      'Test: not the same person',
    );
    await userEvent.click(reject);
    await screen.findByText('Decision saved.');
    expect(callsTo(fetchMock, 'POST', '/api/v1/kyc/attempts/31/decision')[0]?.body).toMatchObject({
      decision: 'reject',
      reason: 'Test: not the same person',
    });
  });

  it('refuses a 12-digit number in the reason before sending', async () => {
    const fetchMock = setup();
    renderApp('/kyc/attempts/31', { user: staffUser });
    await userEvent.type(
      await screen.findByLabelText('Reason (required to reject or ask again)'),
      'Number 1234 5678 9012',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Ask for documents again' }));
    expect(screen.getByRole('alert')).toHaveTextContent('A full 12-digit number is not allowed');
    expect(callsTo(fetchMock, 'POST', '/api/v1/kyc/attempts/31/decision')).toHaveLength(0);
  });

  it('offers Reopen to the owner on a decided check, never to staff', async () => {
    setup(approved);
    renderApp('/kyc/attempts/31', { user: staffUser });
    await screen.findByText(/Decided by Test Staff 001/);
    expect(screen.queryByRole('button', { name: 'Reopen (owner)' })).not.toBeInTheDocument();
  });

  it('lets the owner reopen with a reason', async () => {
    const fetchMock = setup(approved, {
      'POST /api/v1/kyc/attempts/31/reopen': {
        status: 201,
        body: { ...identityAttempt, id: 32, attempt_no: 2, status: 'under_review' },
      },
    });
    renderApp('/kyc/attempts/31', { user: ownerUser });
    await userEvent.click(await screen.findByRole('button', { name: 'Reopen (owner)' }));
    const dialog = screen.getByRole('dialog', { name: 'Reopen this check?' });
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'Test: second look');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reopen (owner)' }));
    await screen.findByText('Reopened as a new attempt.');
    expect(callsTo(fetchMock, 'POST', '/api/v1/kyc/attempts/31/reopen')[0]?.body).toEqual({
      reason: 'Test: second look',
    });
  });
});
