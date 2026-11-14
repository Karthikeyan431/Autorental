import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser, staffUser } from '../../test/users';
import type { Vehicle } from './api';

/** Autos (Week 4): list with papers needing attention, add with a normalised registration
 * number, no way to set "rented" by hand, maintenance cost in paise. Fake data only. */

afterEach(() => {
  vi.unstubAllGlobals();
});

const auto: Vehicle = {
  id: 3,
  registration_number: 'XX00TT0003',
  make: 'DEMO Motors',
  model: 'Test 3W',
  year: 2023,
  fuel_type: 'cng',
  status: 'available',
  selectable: true,
  notes: null,
  papers: [
    {
      id: 11,
      kind: 'insurance',
      number: 'DEMO-INSURANCE-0003',
      valid_from: null,
      valid_until: '2026-11-23',
      document_id: null,
      document_mime_type: null,
      state: 'expiring',
      recorded_by: { id: 2, name: 'Test Staff 001' },
      created_at: '2026-11-13T05:00:00Z',
    },
  ],
  created_by: { id: 2, name: 'Test Staff 001' },
  created_at: '2026-11-13T05:00:00Z',
};

const page = (items: Vehicle[]) => ({ items, total: items.length, page: 1, page_size: 20 });

describe('Autos', () => {
  it('lists autos and shows papers that need attention', async () => {
    mockApi({ 'GET /api/v1/vehicles': { body: page([auto]) } });
    renderApp('/autos', { user: staffUser });
    const row = (await screen.findByRole('link', { name: 'XX00TT0003' })).closest('tr');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('Expiring soon')).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText('Available')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add auto' })).toBeInTheDocument();
  });

  it('hides "Add auto" without vehicles.manage', async () => {
    mockApi({ 'GET /api/v1/vehicles': { body: page([]) } });
    renderApp('/autos', { user: { ...staffUser, permissions: ['drivers.create'] } });
    expect(await screen.findByText('No autos yet.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add auto' })).not.toBeInTheDocument();
  });

  it('sends the registration number normalised', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/vehicles': { body: page([]) },
      'POST /api/v1/vehicles': { status: 201, body: auto },
      'GET /api/v1/vehicles/3': { body: auto },
    });
    const user = userEvent.setup();
    renderApp('/autos', { user: staffUser });
    await user.click(await screen.findByRole('button', { name: 'Add auto' }));
    await user.type(screen.getByLabelText('Registration number'), 'xx 00-tt 0003');
    await user.type(screen.getByLabelText('Make'), 'DEMO Motors');
    await user.type(screen.getByLabelText('Model'), 'Test 3W');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('heading', { name: 'XX00TT0003' })).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/vehicles')[0]?.body).toEqual({
      registration_number: 'XX00TT0003',
      make: 'DEMO Motors',
      model: 'Test 3W',
      year: null,
      fuel_type: null,
      notes: null,
    });
  });

  it('never offers "rented"; a rented auto changes only through its agreement', async () => {
    mockApi({ 'GET /api/v1/vehicles/3': { body: auto } });
    renderApp('/autos/3', { user: staffUser });
    expect(
      await screen.findByRole('button', { name: 'Mark as in maintenance' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mark as inactive' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /rented/i })).not.toBeInTheDocument();
  });

  it('shows no status buttons for a rented auto', async () => {
    mockApi({
      'GET /api/v1/vehicles/3': { body: { ...auto, status: 'rented', selectable: false } },
    });
    renderApp('/autos/3', { user: staffUser });
    expect(
      await screen.findByText('Rented autos change status only through their agreement.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Mark as/ })).not.toBeInTheDocument();
  });

  it('records maintenance with the cost in paise', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/vehicles/3': { body: auto },
      'GET /api/v1/vehicles/3/maintenance': { body: [] },
      'POST /api/v1/vehicles/3/maintenance': {
        status: 201,
        body: {
          id: 1,
          vehicle_id: 3,
          started_on: '2026-11-13',
          ended_on: null,
          description: 'DEMO service',
          cost_paise: 150050,
          recorded_by: { id: 2, name: 'Test Staff 001' },
          created_at: '2026-11-13T05:00:00Z',
        },
      },
    });
    const user = userEvent.setup();
    renderApp('/autos/3', { user: staffUser });
    await user.click(await screen.findByRole('tab', { name: 'Maintenance' }));
    await user.type(screen.getByLabelText('Started on'), '2026-11-13');
    await user.type(screen.getByLabelText('What was done'), 'DEMO service');
    await user.type(screen.getByLabelText('Cost in ₹ (optional)'), '1,500.50');
    await user.click(screen.getByRole('button', { name: 'Record maintenance' }));
    expect(await screen.findByText('Maintenance recorded.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/vehicles/3/maintenance')[0]?.body).toEqual({
      started_on: '2026-11-13',
      ended_on: null,
      description: 'DEMO service',
      cost_paise: 150050,
    });
  });

  it('shows autos and papers on the owner dashboard', async () => {
    mockApi({
      'GET /api/v1/kyc/queue/counts': {
        body: { pending: 0, under_review: 0, resubmission: 0, rejected: 0, expiring: 0 },
      },
      'GET /api/v1/vehicles/summary': {
        body: {
          available: 4,
          rented: 0,
          maintenance: 1,
          inactive: 0,
          papers_expiring: 1,
          papers_expired: 1,
        },
      },
    });
    renderApp('/', { user: ownerUser });
    await waitFor(() => expect(screen.getByTestId('card-Autos available')).toHaveTextContent('4'));
    expect(screen.getByTestId('card-Vehicle papers expiring or expired')).toHaveTextContent('2');
  });
});
