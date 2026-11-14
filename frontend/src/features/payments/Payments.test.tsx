import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiError, callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser, staffUser } from '../../test/users';
import type { ApprovalResult, Payment, PayRequest, Suggestion } from './api';

/** Pay requests and payments (Week 6). Fake data only. */

afterEach(() => {
  vi.unstubAllGlobals();
});

const page = <T,>(items: T[]) => ({ items, total: items.length, page: 1, page_size: 20 });

const request: PayRequest = {
  id: 41,
  driver: { id: 7, code: 'D0007', full_name: 'Test Driver 007' },
  managed_by: { id: 2, name: 'Test Staff 001' },
  agreement_id: 21,
  period_start: '2026-11-05',
  period_end: '2026-11-05',
  amount_paise: 90000,
  reference_code: 'R00071105',
  status: 'open',
  send_count: 0,
  sent_at: null,
  sent_by: null,
  upi_link: 'upi://pay?pa=testautorentals@testbank&am=900.00&cu=INR&tn=R00071105',
  whatsapp_url: 'https://wa.me/919000000007?text=Hello%20Test%20Driver%20007',
  mdr_warning: false,
  awaiting_approval_paise: 0,
  created_at: '2026-11-05T02:30:00Z',
};

const payment: Payment = {
  id: 9,
  driver: { id: 7, code: 'D0007', full_name: 'Test Driver 007' },
  agreement_id: 21,
  amount_paise: 70000,
  method: 'cash',
  source: 'cash_office',
  purpose: 'rent',
  reference: null,
  received_on: '2026-11-05',
  status: 'awaiting_approval',
  recorded_by: { id: 2, name: 'Test Staff 001' },
  recorded_at: '2026-11-05T10:00:00Z',
  approved_by: null,
  approved_at: null,
  rejected_by: null,
  rejected_at: null,
  rejection_reason: null,
  reversed_at: null,
  receipt_no: null,
  receipt_cancelled: false,
  pay_request_id: 41,
  proof_document_id: null,
  allocated_paise: 0,
  unallocated_paise: 70000,
  days_confirmed: false,
  allocations: [],
  pending_reversal_id: null,
  can_confirm_days: true,
};

// The worked example: ₹700 suggested as 2 Nov ₹300, 3 Nov ₹300, 4 Nov ₹100.
const suggestion: Suggestion = {
  unallocated_paise: 70000,
  items: [
    { rent_charge_id: 2, rent_date: '2026-11-02', available_paise: 30000, amount_paise: 30000 },
    { rent_charge_id: 3, rent_date: '2026-11-03', available_paise: 30000, amount_paise: 30000 },
    { rent_charge_id: 4, rent_date: '2026-11-04', available_paise: 30000, amount_paise: 10000 },
    { rent_charge_id: 5, rent_date: '2026-11-05', available_paise: 30000, amount_paise: 0 },
  ],
};

describe('Pay requests today', () => {
  it('shows the amount and sends on WhatsApp with one tap, recording the send', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/pay-requests': { body: [request] },
      'POST /api/v1/pay-requests/41/sent': { body: { ...request, send_count: 1 } },
    });
    const user = userEvent.setup();
    renderApp('/pay-requests', { user: staffUser });
    const card = await screen.findByTestId('pay-request-41');
    expect(within(card).getByText('₹900')).toBeInTheDocument();
    const send = within(card).getByRole('link', { name: 'Send on WhatsApp' });
    expect(send).toHaveAttribute('href', request.whatsapp_url);
    expect(send).toHaveAttribute('target', '_blank');
    send.addEventListener('click', (event) => event.preventDefault()); // no navigation in tests
    await user.click(send);
    await waitFor(() =>
      expect(callsTo(fetchMock, 'POST', '/api/v1/pay-requests/41/sent')).toHaveLength(1),
    );
  });

  it('warns above ₹2,000 and hides Send once paid', async () => {
    mockApi({
      'GET /api/v1/pay-requests': {
        body: [
          { ...request, mdr_warning: true, amount_paise: 210000 },
          { ...request, id: 42, status: 'paid', send_count: 1, sent_at: '2026-11-05T03:00:00Z' },
        ],
      },
    });
    renderApp('/pay-requests', { user: staffUser });
    const weekly = await screen.findByTestId('pay-request-41');
    expect(within(weekly).getByText(/0.4% charge/)).toBeInTheDocument();
    const paid = screen.getByTestId('pay-request-42');
    expect(within(paid).getByText(/Paid/)).toBeInTheDocument();
    expect(within(paid).queryByRole('link', { name: /WhatsApp/ })).not.toBeInTheDocument();
  });

  it('makes today’s requests and explains a missing UPI ID', async () => {
    mockApi({
      'GET /api/v1/pay-requests': { body: [] },
      'POST /api/v1/pay-requests/generate': apiError(
        409,
        'UPI_ID_NOT_SET',
        'Set the business UPI ID in Settings.',
      ),
    });
    const user = userEvent.setup();
    renderApp('/pay-requests', { user: staffUser });
    await user.click(await screen.findByRole('button', { name: 'Make today’s pay requests' }));
    expect(
      await screen.findByText('Set the business UPI ID in Settings first.'),
    ).toBeInTheDocument();
  });

  it('shows the QR full screen for a driver at the office', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/pay-requests': { body: [request] },
      'GET /api/v1/pay-requests/41/qr.png': { body: {} },
    });
    vi.stubGlobal(
      'URL',
      Object.assign(URL, { createObjectURL: () => 'blob:qr', revokeObjectURL: () => undefined }),
    );
    const user = userEvent.setup();
    renderApp('/pay-requests', { user: staffUser });
    await user.click(await screen.findByRole('button', { name: 'Show QR' }));
    expect(
      await screen.findByRole('dialog', { name: 'Scan to pay – R00071105' }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(callsTo(fetchMock, 'GET', '/api/v1/pay-requests/41/qr.png')).toHaveLength(1),
    );
  });
});

describe('Confirm days (rule 4)', () => {
  it('pre-fills the oldest unpaid days and sends nothing until Confirm', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/payments/9': { body: payment },
      'GET /api/v1/payments/9/suggestion': { body: suggestion },
      'PUT /api/v1/payments/9/allocations': {
        body: { ...payment, allocated_paise: 70000, unallocated_paise: 0, days_confirmed: true },
      },
    });
    const user = userEvent.setup();
    renderApp('/payments/9', { user: staffUser });
    expect(await screen.findByLabelText('Apply ₹ 2 Nov 2026')).toHaveValue('300');
    expect(screen.getByLabelText('Apply ₹ 4 Nov 2026')).toHaveValue('100');
    expect(screen.getByLabelText('Apply ₹ 5 Nov 2026')).toHaveValue('');
    expect(screen.getByTestId('days-total')).toHaveTextContent('₹700 of ₹700');
    expect(callsTo(fetchMock, 'PUT', '/api/v1/payments/9/allocations')).toHaveLength(0);

    await user.click(screen.getByRole('button', { name: 'Confirm days' }));
    await waitFor(() =>
      expect(callsTo(fetchMock, 'PUT', '/api/v1/payments/9/allocations')).toHaveLength(1),
    );
    expect(callsTo(fetchMock, 'PUT', '/api/v1/payments/9/allocations')[0]?.body).toEqual({
      items: [
        { rent_charge_id: 2, amount_paise: 30000 },
        { rent_charge_id: 3, amount_paise: 30000 },
        { rent_charge_id: 4, amount_paise: 10000 },
      ],
    });
  });

  it('refuses more than the payment before calling the server', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/payments/9': { body: payment },
      'GET /api/v1/payments/9/suggestion': { body: suggestion },
    });
    const user = userEvent.setup();
    renderApp('/payments/9', { user: staffUser });
    const last = await screen.findByLabelText('Apply ₹ 5 Nov 2026');
    await user.type(last, '300');
    await user.click(screen.getByRole('button', { name: 'Confirm days' }));
    expect(
      await screen.findByText('The days add up to more than the payment.'),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, 'PUT', '/api/v1/payments/9/allocations')).toHaveLength(0);
  });

  it('a recorder who is not the manager sees the payment but not the days (D57)', async () => {
    mockApi({
      'GET /api/v1/payments/9': { body: { ...payment, can_confirm_days: false } },
    });
    renderApp('/payments/9', { user: staffUser });
    expect(
      await screen.findByText('Only the owner or the driver’s manager sees and confirms the days.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm days' })).not.toBeInTheDocument();
  });
});

describe('Owner approval queue (rule 13)', () => {
  it('approves the selected payments and lists the refused ones with the reason', async () => {
    const results: ApprovalResult[] = [
      {
        payment_id: 9,
        outcome: 'approved',
        receipt_no: 'RCPT/2026-27/000001',
        code: null,
        message: null,
      },
      {
        payment_id: 10,
        outcome: 'refused',
        receipt_no: null,
        code: 'PAYMENT_NO_LONGER_FITS',
        message: 'The day 03 Nov 2026 no longer has room for this payment.',
      },
    ];
    const fetchMock = mockApi({
      'GET /api/v1/payments': {
        body: page([payment, { ...payment, id: 10, days_confirmed: true }]),
      },
      'POST /api/v1/payments/approve': { body: results },
    });
    const user = userEvent.setup();
    renderApp('/payments', { user: ownerUser });
    expect(await screen.findByText('Days not confirmed')).toBeInTheDocument();
    await user.click(screen.getByLabelText('Select payment 9'));
    await user.click(screen.getByLabelText('Select payment 10'));
    await user.click(screen.getByRole('button', { name: 'Approve 2 selected' }));
    await waitFor(() =>
      expect(callsTo(fetchMock, 'POST', '/api/v1/payments/approve')[0]?.body).toEqual({
        ids: [9, 10],
      }),
    );
    expect(await screen.findByText(/#10 Not approved: The day 03 Nov 2026/)).toBeInTheDocument();
  });

  it('staff see no approval queue', async () => {
    mockApi({ 'GET /api/v1/payments': { body: page([]) } });
    renderApp('/payments', { user: staffUser });
    expect(await screen.findByRole('tab', { name: 'Record a payment' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Approval queue' })).not.toBeInTheDocument();
  });
});

describe('Record a payment', () => {
  it('needs a proof photo, then sends the payment once with an idempotency key', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/drivers': {
        body: page([{ id: 7, code: 'D0007', full_name: 'Test Driver 007' }]),
      },
      'POST /api/v1/payments': { status: 201, body: payment },
      'GET /api/v1/payments/9': { body: payment },
      'GET /api/v1/payments/9/suggestion': { body: suggestion },
    });
    const user = userEvent.setup();
    renderApp('/payments?tab=record', { user: staffUser });
    await screen.findByRole('option', { name: 'Test Driver 007 (D0007)' });
    await user.selectOptions(screen.getByLabelText('Driver'), '7');
    await user.type(screen.getByLabelText('Amount in ₹'), '700');
    await user.click(screen.getByRole('button', { name: 'Record payment' }));
    expect(await screen.findByText('Add a proof photo.')).toBeInTheDocument();

    const photo = new File(['fake'], 'slip.jpg', { type: 'image/jpeg' });
    await user.upload(screen.getByTestId('capture-camera'), photo);
    await user.click(screen.getByRole('button', { name: 'Record payment' }));
    await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/v1/payments')).toHaveLength(1));
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST');
    const body = call?.[1]?.body as FormData;
    expect(body.get('amount_paise')).toBe('70000');
    expect(body.get('method')).toBe('cash');
    expect(String(body.get('idempotency_key'))).not.toHaveLength(0);
    expect(body.get('proof')).toBeInstanceOf(Blob);
  });
});
