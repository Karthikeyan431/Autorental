import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser } from '../../test/users';

/** Owner dashboard figures. Fake data only. */

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Owner dashboard', () => {
  it('shows active drivers with approved KYC from the drivers list filter (Q28)', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/drivers': { body: { items: [], total: 4, page: 1, page_size: 20 } },
    });
    renderApp('/', { user: ownerUser });
    await waitFor(() =>
      expect(screen.getByTestId('card-Active drivers (KYC approved)')).toHaveTextContent('4'),
    );
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input));
      const call = urls.find((url) => url.startsWith('/api/v1/drivers?'));
      expect(call).toBeDefined();
      const query = new URLSearchParams(call?.split('?')[1]);
      expect(query.get('status')).toBe('active');
      expect(query.get('kyc')).toBe('verified');
      expect(query.has('mine')).toBe(false);
    });
  });

  it('shows payments awaiting approval and today’s pay requests', async () => {
    mockApi({
      'GET /api/v1/payments/summary': {
        body: {
          awaiting_count: 2,
          awaiting_paise: 90000,
          awaiting_days_unconfirmed: 1,
          pending_reversals: 0,
          pending_advance: 0,
          requests_today: 3,
          sent_today: 2,
          paid_today: 1,
          unpaid_today: 2,
        },
      },
    });
    renderApp('/', { user: ownerUser });
    await waitFor(() =>
      expect(screen.getByTestId('card-Payments awaiting approval')).toHaveTextContent('2 · ₹900'),
    );
    expect(screen.getByTestId('card-Pay requests today')).toHaveTextContent(
      '2 sent · 1 paid · 2 unpaid',
    );
  });
});
