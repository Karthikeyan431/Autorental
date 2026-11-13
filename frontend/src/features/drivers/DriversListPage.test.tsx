import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { ownerUser, staffUser } from '../../test/users';

afterEach(() => {
  vi.unstubAllGlobals();
});

const rows = [
  {
    id: 7,
    code: 'D0007',
    full_name: 'Test Driver 007',
    mobile: '+919000000007',
    account_status: 'active',
    photo_document_id: null,
    created_by: { id: 2, name: 'Test Staff 001' },
    managed_by: { id: 2, name: 'Test Staff 001' },
    identity_status: 'approved',
    licence_status: 'submitted',
  },
  {
    id: 8,
    code: 'D0008',
    full_name: 'Test Driver 008',
    mobile: '+919000000008',
    account_status: 'active',
    photo_document_id: null,
    created_by: { id: 3, name: 'Test Staff 002' },
    managed_by: { id: 3, name: 'Test Staff 002' },
    identity_status: null,
    licence_status: null,
  },
];

function setup() {
  return mockApi({
    'GET /api/v1/drivers': { body: { items: rows, total: 2, page: 1, page_size: 20 } },
    'GET /api/v1/drivers/managers': {
      body: [
        { id: 2, name: 'Test Staff 001' },
        { id: 3, name: 'Test Staff 002' },
      ],
    },
  });
}

function lastQuery(fetchMock: ReturnType<typeof mockApi>): URLSearchParams {
  const urls = fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.startsWith('/api/v1/drivers?'));
  return new URLSearchParams(urls.at(-1)?.split('?')[1]);
}

describe('Drivers list', () => {
  it('starts on "Managed by me" for staff', async () => {
    const fetchMock = setup();
    renderApp('/drivers', { user: staffUser });
    expect(await screen.findByText('D0007 · Test Driver 007')).toBeInTheDocument();
    expect(screen.getByLabelText('Managed by')).toHaveValue('me');
    expect(lastQuery(fetchMock).get('mine')).toBe('true');
  });

  it('filters by manager for the owner and hides KYC it cannot show', async () => {
    const fetchMock = setup();
    renderApp('/drivers', { user: ownerUser });
    await screen.findByText('D0008 · Test Driver 008');
    expect(lastQuery(fetchMock).get('mine')).toBeNull();
    expect(screen.getByText('Approved')).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText('Managed by'), '3');
    expect(lastQuery(fetchMock).get('managed_by')).toBe('3');
    await userEvent.selectOptions(screen.getByLabelText('KYC'), 'verified');
    expect(lastQuery(fetchMock).get('kyc')).toBe('verified');
  });
});
