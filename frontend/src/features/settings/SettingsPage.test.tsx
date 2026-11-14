import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser } from '../../test/users';

const version = {
  id: 1,
  effective_from: '2026-11-13T04:30:00Z',
  created_at: '2026-11-13T04:30:00Z',
  created_by: null,
  created_by_name: null,
  rent_due_time: '10:00:00',
  due_day_offset: 0,
  licence_alert_days: 30,
  vehicle_alert_days: 30,
  permitted_licence_classes: [],
  accepted_id_types: ['masked_aadhaar'],
  advance_adjustments_enabled: true,
  refunds_enabled: false,
  staff_limit: 10,
  reveal_limit_per_hour: 30,
  max_backdate_days: 7,
  business_name: 'Test Auto Rentals (DEMO)',
  business_address: null,
  business_upi_id: 'demo@upi',
  upi_payee_name: 'DEMO Payee',
  whatsapp_template: 'Hello {name}',
  pay_request_time: '08:00:00',
  weekly_pay_day: 1,
  escalation_suggest_after_days: 1,
  weekly_mdr_warning_paise: 200000,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Settings page', () => {
  it('saves only the changed fields as a new version after confirmation', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/settings/current': { body: version },
      'GET /api/v1/settings/versions': {
        body: { items: [version], total: 1, page: 1, page_size: 10 },
      },
      'POST /api/v1/settings': { status: 201, body: { ...version, id: 2, staff_limit: 11 } },
    });
    renderApp('/settings', { user: ownerUser });

    const limit = await screen.findByLabelText('Staff limit (active staff accounts)');
    expect(screen.getByLabelText('Warn when a weekly pay request is above (₹)')).toHaveValue(
      '2000',
    );
    await userEvent.clear(limit);
    await userEvent.type(limit, '11');
    await userEvent.click(screen.getByRole('button', { name: 'Save as a new version' }));

    const dialog = screen.getByRole('dialog', { name: 'Save a new settings version?' });
    await userEvent.type(
      within(dialog).getByLabelText('Reason for this change (optional)'),
      'Hiring',
    );
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save version' }));

    expect(await screen.findByText('Settings saved as a new version.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/settings')[0]?.body).toEqual({
      staff_limit: 11,
      reason: 'Hiring',
    });
  });

  it('sends the warning amount as integer paise', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/settings/current': { body: version },
      'GET /api/v1/settings/versions': {
        body: { items: [version], total: 1, page: 1, page_size: 10 },
      },
      'POST /api/v1/settings': { status: 201, body: version },
    });
    renderApp('/settings', { user: ownerUser });
    const amount = await screen.findByLabelText('Warn when a weekly pay request is above (₹)');
    await userEvent.clear(amount);
    await userEvent.type(amount, '1999.50');
    await userEvent.click(screen.getByRole('button', { name: 'Save as a new version' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save version' }));
    await screen.findByText('Settings saved as a new version.');
    expect(callsTo(fetchMock, 'POST', '/api/v1/settings')[0]?.body).toEqual({
      weekly_mdr_warning_paise: 199950,
      reason: null,
    });
  });

  it('says nothing changed instead of saving an identical version', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/settings/current': { body: version },
      'GET /api/v1/settings/versions': {
        body: { items: [version], total: 1, page: 1, page_size: 10 },
      },
    });
    renderApp('/settings', { user: ownerUser });
    await screen.findByLabelText('Staff limit (active staff accounts)');
    await userEvent.click(screen.getByRole('button', { name: 'Save as a new version' }));
    expect(await screen.findByText('Nothing has changed.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/settings')).toHaveLength(0);
  });

  it('shows the version history', async () => {
    mockApi({
      'GET /api/v1/settings/current': { body: version },
      'GET /api/v1/settings/versions': {
        body: { items: [version], total: 1, page: 1, page_size: 10 },
      },
    });
    renderApp('/settings', { user: ownerUser });
    const table = await screen.findByRole('table', { name: 'Version history' });
    expect(within(table).getByText('System')).toBeInTheDocument();
    expect(within(table).getByText('₹2,000')).toBeInTheDocument();
  });
});

describe('Settings page: accepted ID documents (N12)', () => {
  it('sends the accepted ID documents when one is added', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/settings/current': { body: version },
      'GET /api/v1/settings/versions': {
        body: { items: [version], total: 1, page: 1, page_size: 10 },
      },
      'POST /api/v1/settings': { status: 201, body: version },
    });
    renderApp('/settings', { user: ownerUser });
    const voter = await screen.findByRole('checkbox', { name: 'Voter ID' });
    expect(screen.getByRole('checkbox', { name: 'Masked Aadhaar' })).toBeChecked();
    await userEvent.click(voter);
    await userEvent.click(screen.getByRole('button', { name: 'Save as a new version' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Save version' }));
    await screen.findByText('Settings saved as a new version.');
    expect(callsTo(fetchMock, 'POST', '/api/v1/settings')[0]?.body).toEqual({
      accepted_id_types: ['masked_aadhaar', 'voter_id'],
      reason: null,
    });
  });
});
