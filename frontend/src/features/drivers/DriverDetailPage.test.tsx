import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { driver, driverKyc } from '../../test/drivers';
import { callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser, staffUser } from '../../test/users';

afterEach(() => {
  vi.unstubAllGlobals();
});

const timelineAfter = [
  {
    id: 12,
    at: '2026-11-13T05:00:00Z',
    action: 'driver.manager_changed',
    entity_type: 'driver',
    entity_id: 7,
    actor: { id: 1, name: 'Test Owner' },
    reason: 'Test: area change',
  },
  {
    id: 10,
    at: '2026-11-10T05:00:00Z',
    action: 'driver.created',
    entity_type: 'driver',
    entity_id: 7,
    actor: { id: 2, name: 'Test Staff 001' },
    reason: null,
  },
];

function setup(extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({
    'GET /api/v1/drivers/7': { body: driver },
    'GET /api/v1/drivers/managers': {
      body: [
        { id: 1, name: 'Test Owner' },
        { id: 2, name: 'Test Staff 001' },
        { id: 3, name: 'Test Staff 002' },
      ],
    },
    'GET /api/v1/drivers/7/kyc': { body: driverKyc },
    'GET /api/v1/drivers/7/eligibility': {
      body: {
        driver_id: 7,
        on_date: '2026-11-13',
        ok: false,
        reasons: ['IDENTITY_NOT_APPROVED', 'LICENCE_NOT_APPROVED'],
        messages: [],
        licence_valid_until: null,
      },
    },
    ...extra,
  });
}

describe('Driver page', () => {
  it('shows Created by and Managed by in the header', async () => {
    setup();
    renderApp('/drivers/7', { user: staffUser });
    expect(await screen.findByRole('heading', { name: 'Test Driver 007' })).toBeInTheDocument();
    expect(screen.getByTestId('created-by')).toHaveTextContent('Test Staff 001 on 10 Nov 2026');
    expect(screen.getByTestId('managed-by')).toHaveTextContent('Test Staff 001 since 10 Nov 2026');
  });

  it('offers Change manager to the owner only', async () => {
    setup();
    renderApp('/drivers/7', { user: staffUser });
    await screen.findByRole('heading', { name: 'Test Driver 007' });
    expect(screen.queryByRole('button', { name: 'Change manager' })).not.toBeInTheDocument();
  });

  it('lets the owner change the manager with a reason; the activity lists it', async () => {
    const fetchMock = setup({
      'POST /api/v1/drivers/7/manager': {
        body: {
          ...driver,
          managed_by: { id: 3, name: 'Test Staff 002' },
          managed_since: '2026-11-13T05:00:00Z',
        },
      },
      'GET /api/v1/drivers/7/timeline': { body: timelineAfter },
      'GET /api/v1/drivers/7/manager-history': {
        body: [
          {
            id: 2,
            staff: { id: 3, name: 'Test Staff 002' },
            from_at: '2026-11-13T05:00:00Z',
            to_at: null,
            changed_by: { id: 1, name: 'Test Owner' },
            reason: 'Test: area change',
          },
          {
            id: 1,
            staff: { id: 2, name: 'Test Staff 001' },
            from_at: '2026-11-10T05:00:00Z',
            to_at: '2026-11-13T05:00:00Z',
            changed_by: { id: 2, name: 'Test Staff 001' },
            reason: null,
          },
        ],
      },
    });
    renderApp('/drivers/7', { user: ownerUser });
    await userEvent.click(await screen.findByRole('button', { name: 'Change manager' }));
    const dialog = screen.getByRole('dialog', { name: 'Change the managing staff member' });

    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Give a reason.');

    await userEvent.selectOptions(within(dialog).getByLabelText('New manager'), '3');
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'Test: area change');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Manager changed.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/drivers/7/manager')[0]?.body).toEqual({
      staff_id: 3,
      reason: 'Test: area change',
    });
    expect(screen.getByTestId('managed-by')).toHaveTextContent('Test Staff 002');

    await userEvent.click(screen.getByRole('tab', { name: 'Activity' }));
    const activity = await screen.findByTestId('activity');
    expect(within(activity).getByText('Manager changed')).toBeInTheDocument();
    expect(within(activity).getByText(/Test: area change/)).toBeInTheDocument();
    const history = await screen.findByTestId('manager-history');
    expect(within(history).getByText('Test Staff 002 (current)')).toBeInTheDocument();
  });

  it('hides KYC from staff who cannot see it', async () => {
    setup({
      'GET /api/v1/drivers/7': {
        body: { ...driver, can_edit: false, can_view_kyc: false, identity_status: null },
      },
    });
    renderApp('/drivers/7', { user: staffUser });
    await userEvent.click(await screen.findByRole('tab', { name: 'KYC and documents' }));
    expect(
      screen.getByText(/Only the owner, the managing staff member and staff who can edit/),
    ).toBeInTheDocument();
  });

  it('shows the eligibility reasons on the KYC tab', async () => {
    setup();
    renderApp('/drivers/7', { user: staffUser });
    await userEvent.click(await screen.findByRole('tab', { name: 'KYC and documents' }));
    const reasons = await screen.findByTestId('eligibility-reasons');
    expect(within(reasons).getByText('Identity is not approved.')).toBeInTheDocument();
    expect(within(reasons).getByText('Licence is not approved.')).toBeInTheDocument();
  });
});
