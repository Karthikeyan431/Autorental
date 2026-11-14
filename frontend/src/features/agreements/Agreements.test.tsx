import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiError, callsTo, mockApi } from '../../test/mock-api';
import { driver } from '../../test/drivers';
import { renderApp } from '../../test/render';
import { ownerUser, staffUser } from '../../test/users';
import type { Vehicle } from '../autos/api';
import type { Agreement, Ledger, LedgerRow, RentSummary } from './api';
import { dayLabel, dayTone } from './ledger';

/** Agreements and the rent ledger (Week 5). Fake data only. */

afterEach(() => {
  vi.unstubAllGlobals();
});

const page = <T,>(items: T[]) => ({ items, total: items.length, page: 1, page_size: 20 });

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
  papers: [],
  created_by: null,
  created_at: '2026-11-13T05:00:00Z',
};

const agreement: Agreement = {
  id: 21,
  agreement_no: 'AG000021',
  status: 'active',
  driver: { id: 7, code: 'D0007', full_name: 'Test Driver 007', managed_by: null },
  vehicle: {
    id: 3,
    registration_number: 'XX00TT0003',
    make: 'DEMO',
    model: 'Test 3W',
    status: 'rented',
  },
  start_date: '2026-11-02',
  end_date: null,
  daily_rent_paise: 30000,
  advance_required_paise: 200000,
  terms_version: 'placeholder-v1',
  signed_document_id: null,
  created_by: { id: 2, name: 'Test Staff 001' },
  created_at: '2026-11-02T04:00:00Z',
  activated_by: { id: 2, name: 'Test Staff 001' },
  activated_at: '2026-11-02T04:00:00Z',
  ended_by: null,
  ended_at: null,
  end_reason: null,
  cancelled_by: null,
  cancelled_at: null,
  cancel_reason: null,
  vehicle_available_from: null,
};

function day(rent_date: string, allocated: number, status: LedgerRow['status'], overdue: boolean) {
  return {
    charge_id: Number(rent_date.slice(-2)),
    agreement_id: 21,
    agreement_no: 'AG000021',
    rent_date,
    due_at: `${rent_date}T04:30:00Z`,
    charge_paise: 30000,
    adjustments_paise: 0,
    pending_adjustments_paise: 0,
    allocated_paise: allocated,
    awaiting_approval_paise: 0,
    balance_paise: 30000 - allocated,
    status,
    is_overdue: overdue,
    pending_adjustment_ids: [],
  } satisfies LedgerRow;
}

// The worked example in docs/rent-and-payments.md §1, at 18:00 on 5 November 2026.
const workedExample: Ledger = {
  driver_id: 7,
  as_of: '2026-11-05T12:30:00Z',
  rows: [
    day('2026-11-02', 30000, 'paid', false),
    day('2026-11-03', 30000, 'paid', false),
    day('2026-11-04', 10000, 'part_paid', true),
    day('2026-11-05', 0, 'unpaid', true),
  ],
  totals: {
    charge_paise: 120000,
    adjustments_paise: 0,
    allocated_paise: 70000,
    balance_paise: 50000,
  },
  outstanding_paise: 50000,
  overdue_paise: 50000,
};

describe('day labels', () => {
  it('names Paid, Part paid, Unpaid, Overdue and Waived', () => {
    expect(dayLabel({ status: 'paid', is_overdue: false })).toBe('Paid');
    expect(dayLabel({ status: 'part_paid', is_overdue: true })).toBe('Part paid, overdue');
    expect(dayLabel({ status: 'unpaid', is_overdue: true })).toBe('Unpaid, overdue');
    expect(dayLabel({ status: 'waived', is_overdue: false })).toBe('Waived');
    expect(dayTone({ status: 'unpaid', is_overdue: true })).toBe('bad');
    expect(dayTone({ status: 'paid', is_overdue: false })).toBe('ok');
  });
});

describe('Rent ledger tab', () => {
  it('shows the worked example with statuses, right-aligned money and totals', async () => {
    mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/ledger': { body: workedExample },
    });
    const user = userEvent.setup();
    renderApp('/drivers/7', { user: staffUser });
    await user.click(await screen.findByRole('tab', { name: 'Rent ledger' }));

    const table = await screen.findByRole('table', { name: 'Rent ledger' });
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(4);
    expect(within(rows[2] as HTMLElement).getByText('Part paid, overdue')).toBeInTheDocument();
    expect(within(rows[3] as HTMLElement).getByText('Unpaid, overdue')).toBeInTheDocument();
    const balance = within(rows[2] as HTMLElement).getByText('₹200');
    expect(balance.closest('td')).toHaveClass('text-right');
    const position = screen.getByTestId('ledger-position');
    expect(within(position).getAllByText('₹500')).toHaveLength(2); // outstanding and overdue
    expect(screen.getByTestId('ledger-totals')).toHaveTextContent('Charge ₹1,200');
  });

  it("says so when the user may not see this driver's rent (N1)", async () => {
    mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/ledger': apiError(404, 'NOT_FOUND', 'Not found.'),
    });
    const user = userEvent.setup();
    renderApp('/drivers/7', { user: staffUser });
    await user.click(await screen.findByRole('tab', { name: 'Rent ledger' }));
    expect(
      await screen.findByText("Only the owner and the driver's manager see this driver's rent."),
    ).toBeInTheDocument();
  });

  it('sends a waiver request in signed paise', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/ledger': { body: workedExample },
      'POST /api/v1/rent/charges/5/adjustments': { status: 201, body: {} },
    });
    const user = userEvent.setup();
    renderApp('/drivers/7', { user: staffUser });
    await user.click(await screen.findByRole('tab', { name: 'Rent ledger' }));
    const rows = within(await screen.findByRole('table', { name: 'Rent ledger' })).getAllByRole(
      'row',
    );
    await user.click(within(rows[4] as HTMLElement).getByRole('button', { name: 'Adjust' }));
    const amount = screen.getByLabelText('Amount in ₹ (negative to waive)');
    expect(amount).toHaveValue('-300');
    await user.type(screen.getByLabelText('Reason'), 'Auto off the road for repairs');
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Adjust' }));
    await waitFor(() =>
      expect(callsTo(fetchMock, 'POST', '/api/v1/rent/charges/5/adjustments')[0]?.body).toEqual({
        amount_paise: -30000,
        reason: 'Auto off the road for repairs',
      }),
    );
  });
});

describe('New agreement', () => {
  const routes = (eligibility: unknown) => ({
    'GET /api/v1/drivers': { body: page([driver]) },
    'GET /api/v1/vehicles': { body: page([auto]) },
    'GET /api/v1/agreements/eligibility': { body: eligibility },
    'POST /api/v1/agreements': { status: 201, body: { ...agreement, status: 'draft' } },
    'POST /api/v1/agreements/21/activate': { body: agreement },
    'GET /api/v1/agreements/21': { body: agreement },
  });

  async function fill(user: ReturnType<typeof userEvent.setup>) {
    await screen.findByRole('option', { name: 'Test Driver 007 (D0007)' });
    await user.selectOptions(screen.getByLabelText('Driver'), '7');
    await screen.findByRole('option', { name: 'XX00TT0003 · DEMO Motors Test 3W' });
    await user.selectOptions(screen.getByLabelText('Auto (available only)'), '3');
    await user.type(screen.getByLabelText('Daily rent in ₹'), '300');
  }

  it('shows every reason and will not activate an ineligible driver', async () => {
    mockApi(
      routes({
        ok: false,
        reasons: [
          { code: 'LICENCE_EXPIRED', message: 'The licence is not valid on this date.' },
          { code: 'VEHICLE_RETURNED_ON_START', message: 'The auto was returned on this date.' },
        ],
        vehicle_available_from: '2026-11-14',
        max_backdate_days: 7,
      }),
    );
    const user = userEvent.setup();
    renderApp('/agreements/new', { user: staffUser });
    await fill(user);
    const reasons = await screen.findByTestId('eligibility-reasons');
    expect(within(reasons).getByText('The licence is not valid on this date.')).toBeInTheDocument();
    expect(within(reasons).getByText('Available from 14 Nov 2026')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Review' }));
    expect(screen.getByRole('button', { name: 'Confirm and activate' })).toBeDisabled();
  });

  it('creates and activates with the rate in paise', async () => {
    const fetchMock = mockApi(
      routes({ ok: true, reasons: [], vehicle_available_from: null, max_backdate_days: 7 }),
    );
    const user = userEvent.setup();
    renderApp('/agreements/new', { user: staffUser });
    await fill(user);
    expect(
      await screen.findByText('This driver can take this auto from the start date.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Review' }));
    await user.click(screen.getByRole('button', { name: 'Confirm and activate' }));
    expect(await screen.findByRole('heading', { name: 'Agreement AG000021' })).toBeInTheDocument();
    const body = callsTo(fetchMock, 'POST', '/api/v1/agreements')[0]?.body as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({ driver_id: 7, vehicle_id: 3, daily_rent_paise: 30000 });
    expect(callsTo(fetchMock, 'POST', '/api/v1/agreements/21/activate')).toHaveLength(1);
  });
});

describe('Owner dashboard', () => {
  it('shows rent expected today and overdue figures in rupees', async () => {
    const summary: RentSummary = {
      scope: 'all',
      as_of: '2026-11-05T12:30:00Z',
      rent_expected_today_paise: 120000,
      active_agreements: 4,
      overdue_drivers: 1,
      overdue_paise: 50000,
      adjustments_pending: 0,
    };
    mockApi({
      'GET /api/v1/rent/summary': { body: summary },
      'GET /api/v1/rent/overdue': {
        body: [
          {
            driver_id: 7,
            driver_code: 'D0007',
            driver_name: 'Test Driver 007',
            managed_by: { id: 2, name: 'Test Staff 001' },
            overdue_paise: 50000,
            outstanding_paise: 50000,
            awaiting_approval_paise: 0,
            oldest_overdue_date: '2026-11-04',
            days_overdue: 1,
          },
        ],
      },
      'GET /api/v1/adjustments': { body: [] },
    });
    renderApp('/', { user: ownerUser });
    await waitFor(() =>
      expect(screen.getByTestId('card-Rent expected today')).toHaveTextContent('₹1,200'),
    );
    expect(screen.getByTestId('card-Overdue rent')).toHaveTextContent('₹500');
    expect(screen.getByTestId('card-Drivers with overdue rent')).toHaveTextContent('1');
    const missed = await screen.findByRole('table', { name: 'Missed rent' });
    expect(within(missed).getByText('4 Nov 2026 (1 day)')).toBeInTheDocument();
  });
});

describe('Agreement page', () => {
  it('ends an agreement and reports the waivers left for the owner', async () => {
    const ended: Agreement = {
      ...agreement,
      status: 'ended',
      end_date: '2026-11-12',
      vehicle_available_from: '2026-11-13',
    };
    const fetchMock = mockApi({
      'GET /api/v1/agreements/21': [{ body: agreement }, { body: ended }],
      'POST /api/v1/agreements/21/end': { body: { agreement: ended, waivers_created: 1 } },
    });
    const user = userEvent.setup();
    renderApp('/agreements/21', { user: staffUser });
    await user.click(await screen.findByRole('button', { name: 'End agreement' }));
    const dialog = screen.getByRole('dialog');
    const date = within(dialog).getByLabelText('Return date');
    await user.clear(date);
    await user.type(date, '2026-11-12');
    await user.click(within(dialog).getByRole('button', { name: 'End agreement' }));
    expect(
      await screen.findByText(
        'Agreement ended. 1 charge after the return day awaits the owner as a waiver.',
      ),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/agreements/21/end')[0]?.body).toEqual({
      end_date: '2026-11-12',
      reason: null,
    });
    expect(await screen.findByText('Available from 13 Nov 2026')).toBeInTheDocument();
  });
});
