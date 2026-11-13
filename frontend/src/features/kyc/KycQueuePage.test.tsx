import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser } from '../../test/users';

afterEach(() => {
  vi.unstubAllGlobals();
});

const item = (overrides: Record<string, unknown>) => ({
  driver: {
    id: 7,
    code: 'D0007',
    full_name: 'Test Driver 007',
    managed_by: { id: 2, name: 'Test Staff 001' },
  },
  check_type: 'identity',
  bucket: 'under_review',
  attempt_id: 31,
  attempt_no: 1,
  status: 'submitted',
  submitted_at: '2026-11-10T06:00:00Z',
  licence_valid_until: null,
  ...overrides,
});

describe('KYC queue', () => {
  it('shows each tab with its count and links to the review', async () => {
    mockApi({
      'GET /api/v1/kyc/queue/counts': {
        body: { pending: 2, under_review: 1, resubmission: 0, rejected: 0, expiring: 1 },
      },
      'GET /api/v1/kyc/queue': [
        { body: { items: [item({})], total: 1, page: 1, page_size: 20 } },
        {
          body: {
            items: [
              item({
                check_type: 'licence',
                bucket: 'pending',
                attempt_id: null,
                attempt_no: null,
                status: null,
                submitted_at: null,
              }),
            ],
            total: 1,
            page: 1,
            page_size: 20,
          },
        },
      ],
    });
    renderApp('/kyc', { user: ownerUser });
    expect(await screen.findByRole('tab', { name: 'Under review (1)' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Expiring (1)' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Review' })).toHaveAttribute(
      'href',
      '/kyc/attempts/31',
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Pending (2)' }));
    expect(await screen.findByRole('link', { name: 'Continue onboarding' })).toHaveAttribute(
      'href',
      '/drivers/new?driver=7&step=4',
    );
  });
});
