import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { driver, driverKyc } from '../../test/drivers';
import { callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { staffUser } from '../../test/users';

/** Masked identity fields (D45, D46, N17): masked by default, "Show" only for the owner and the
 * current manager, the value kept only on the screen, and edits that never pre-fill them. */

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.sessionStorage.clear();
});

const FAKE_ADDRESS = 'Test address 007, Demo Nagar';

function setup(overrides: Partial<typeof driver> = {}) {
  return mockApi({
    'GET /api/v1/drivers/7': { body: { ...driver, ...overrides } },
    'GET /api/v1/drivers/managers': { body: [] },
    'GET /api/v1/drivers/7/kyc': { body: driverKyc },
    'GET /api/v1/drivers/7/timeline': { body: [] },
    'GET /api/v1/drivers/7/manager-history': { body: [] },
    'POST /api/v1/drivers/7/reveal': { body: { field: 'address', value: FAKE_ADDRESS } },
    'PATCH /api/v1/drivers/7': { body: { ...driver, ...overrides } },
  });
}

describe('Masked identity fields', () => {
  it('shows the address and date of birth masked by default', async () => {
    setup();
    renderApp('/drivers/7', { user: staffUser });
    expect(await screen.findByTestId('masked-address')).toHaveTextContent('••••••');
    expect(screen.getByTestId('masked-date_of_birth')).toHaveTextContent('••••••');
    expect(screen.queryByText(FAKE_ADDRESS)).not.toBeInTheDocument();
  });

  it('offers Show only to the owner or the current manager', async () => {
    setup({ can_reveal: false });
    renderApp('/drivers/7', { user: staffUser });
    await screen.findByTestId('masked-address');
    expect(screen.queryByRole('button', { name: 'Show address' })).not.toBeInTheDocument();
  });

  it('reveals one field on Show and forgets it after leaving the screen', async () => {
    const fetchMock = setup();
    const user = userEvent.setup();
    renderApp('/drivers/7', { user: staffUser });
    await user.click(await screen.findByRole('button', { name: 'Show address' }));
    expect(await screen.findByText(FAKE_ADDRESS)).toBeInTheDocument();
    const calls = callsTo(fetchMock, 'POST', '/api/v1/drivers/7/reveal');
    expect(calls).toHaveLength(1);
    expect(calls[0]?.body).toEqual({ field: 'address' });

    // Leave the details tab and come back: the value is gone.
    await user.click(screen.getByRole('tab', { name: 'Activity' }));
    await user.click(screen.getByRole('tab', { name: 'Details' }));
    expect(await screen.findByTestId('masked-address')).toHaveTextContent('••••••');
    expect(screen.queryByText(FAKE_ADDRESS)).not.toBeInTheDocument();
    // Never written to browser storage.
    const stored = JSON.stringify({ ...window.localStorage, ...window.sessionStorage });
    expect(stored).not.toContain(FAKE_ADDRESS);
  });

  it('does not pre-fill masked fields when editing and does not send them when blank', async () => {
    const fetchMock = setup();
    const user = userEvent.setup();
    renderApp('/drivers/7', { user: staffUser });
    await user.click(await screen.findByRole('button', { name: 'Edit details' }));
    const address = screen.getByLabelText('Address');
    expect(address).toHaveValue('');
    expect(screen.getAllByText('Leave blank to keep the current value.').length).toBeGreaterThan(0);
    await user.click(screen.getByRole('button', { name: 'Save' }));
    const patches = callsTo(fetchMock, 'PATCH', '/api/v1/drivers/7');
    expect(patches).toHaveLength(1);
    expect(patches[0]?.body).not.toHaveProperty('address');
    expect(patches[0]?.body).not.toHaveProperty('date_of_birth');
  });

  it('hides the masked inputs from staff who are not the manager', async () => {
    setup({ can_reveal: false });
    const user = userEvent.setup();
    renderApp('/drivers/7', { user: staffUser });
    await user.click(await screen.findByRole('button', { name: 'Edit details' }));
    expect(screen.queryByLabelText('Address')).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Only the owner or the driver's manager can change the address or date of birth.",
      ),
    ).toBeInTheDocument();
  });

  it('hides KYC documents and the decision from staff who do not manage the driver', async () => {
    mockApi({
      'GET /api/v1/drivers/7': { body: { ...driver, can_reveal: false } },
      'GET /api/v1/drivers/managers': { body: [] },
      'GET /api/v1/drivers/7/kyc': {
        body: {
          ...driverKyc,
          identity: {
            ...driverKyc.identity,
            documents: [
              {
                id: 5,
                owner_type: 'kyc_check',
                owner_id: 31,
                doc_type: 'id_front',
                mime_type: 'image/jpeg',
                size_bytes: 10,
                uploaded_at: '2026-11-10T05:40:00Z',
                content_url: '/api/v1/documents/5/content',
              },
            ],
          },
          can_reveal: false,
          can_capture: false,
          can_decide: false,
          can_view_documents: false,
        },
      },
      'GET /api/v1/drivers/7/eligibility': {
        body: {
          driver_id: 7,
          on_date: '2026-11-13',
          ok: false,
          reasons: [],
          messages: [],
          licence_valid_until: null,
        },
      },
    });
    const user = userEvent.setup();
    renderApp('/drivers/7', { user: staffUser });
    await user.click(await screen.findByRole('tab', { name: 'KYC and documents' }));
    const panel = await screen.findByRole('tabpanel');
    expect(
      await within(panel).findByText(/Only the owner or the driver's manager can open KYC/),
    ).toBeInTheDocument();
    expect(
      within(panel).getByText("Only the owner or the driver's manager can decide this check."),
    ).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    expect(
      within(panel).queryByRole('link', { name: 'Continue onboarding' }),
    ).not.toBeInTheDocument();
  });
});
