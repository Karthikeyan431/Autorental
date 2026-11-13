import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { driver, driverKyc } from '../../test/drivers';
import { callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { staffUser } from '../../test/users';

afterEach(() => {
  vi.unstubAllGlobals();
});

async function fillDetails(address: string) {
  await userEvent.type(screen.getByLabelText('Full name'), 'Test Driver 007');
  await userEvent.type(screen.getByLabelText('Mobile'), '9000000007');
  await userEvent.type(screen.getByLabelText('Date of birth'), '1990-01-01');
  await userEvent.type(screen.getByLabelText('Address'), address);
}

describe('Register driver wizard', () => {
  it('saves the details as a draft and moves to the photo step', async () => {
    const fetchMock = mockApi({
      'POST /api/v1/drivers': { status: 201, body: { ...driver, identity_status: null } },
      'GET /api/v1/drivers/7': { body: { ...driver, identity_status: null } },
    });
    renderApp('/drivers/new', { user: staffUser });
    await fillDetails('Test address 007, Demo Nagar');
    await userEvent.click(screen.getByRole('button', { name: 'Save and continue' }));

    expect(await screen.findByText('Step 2 of 6')).toBeInTheDocument();
    expect(await screen.findByText('D0007 · Test Driver 007')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/drivers')[0]?.body).toEqual({
      full_name: 'Test Driver 007',
      mobile: '9000000007',
      alt_mobile: null,
      address: 'Test address 007, Demo Nagar',
      date_of_birth: '1990-01-01',
      emergency_name: null,
      emergency_mobile: null,
      payment_rhythm: 'daily',
    });
  });

  it('refuses a full 12-digit number in any field', async () => {
    const fetchMock = mockApi({});
    renderApp('/drivers/new', { user: staffUser });
    await fillDetails('Plot 1234 5678 9012');
    await userEvent.click(screen.getByRole('button', { name: 'Save and continue' }));
    expect(await screen.findByText(/A full 12-digit number is not allowed/)).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/drivers')).toHaveLength(0);
  });

  it('opens the phone camera for the photo; the live camera is hidden over plain http', async () => {
    mockApi({ 'GET /api/v1/drivers/7': { body: driver } });
    renderApp('/drivers/new?driver=7&step=1', { user: staffUser });
    expect(await screen.findByRole('button', { name: 'Take photo: Driver photo' })).toBeVisible();
    const camera = screen.getByTestId('capture-camera');
    expect(camera).toHaveAttribute('accept', 'image/*');
    expect(camera).toHaveAttribute('capture', 'environment');
    expect(screen.queryByRole('button', { name: /Use live camera/ })).not.toBeInTheDocument();
  });

  it('uploads the photo taken with the camera', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'POST /api/v1/drivers/7/photo': { body: { ...driver, photo_document_id: 99 } },
    });
    renderApp('/drivers/new?driver=7&step=1', { user: staffUser });
    await screen.findByRole('button', { name: 'Take photo: Driver photo' });
    const photo = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'photo.jpg', {
      type: 'image/jpeg',
    });
    await userEvent.upload(screen.getByTestId('capture-camera'), photo);
    expect(await screen.findByText('Photo saved.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/drivers/7/photo')).toHaveLength(1);
  });

  it('records consent before identity', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/kyc': [
        {
          body: { ...driverKyc, identity: null, history: [], consents: [], has_kyc_consent: false },
        },
        { body: driverKyc },
      ],
      'POST /api/v1/drivers/7/consents': { status: 201, body: driverKyc.consents[0] },
    });
    renderApp('/drivers/new?driver=7&step=2', { user: staffUser });
    const record = await screen.findByRole('button', { name: 'Record consent' });
    expect(record).toBeDisabled();
    await userEvent.click(
      screen.getByRole('checkbox', { name: 'The driver agreed after hearing the notice' }),
    );
    await userEvent.click(record);
    expect(await screen.findByText(/Consent recorded/)).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/drivers/7/consents')[0]?.body).toEqual({
      purpose: 'kyc',
      notice_version: 'kyc-notice-v1',
      method: 'in_person_checkbox',
    });
  });

  it('asks for consent first on the identity step', async () => {
    mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/kyc': {
        body: { ...driverKyc, identity: null, history: [], consents: [], has_kyc_consent: false },
      },
    });
    renderApp('/drivers/new?driver=7&step=3', { user: staffUser });
    expect(
      await screen.findByText('Record consent before identity and licence checks.'),
    ).toBeInTheDocument();
  });

  it('refuses more than 4 digits for the identity number', async () => {
    const fetchMock = mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/kyc': {
        body: { ...driverKyc, identity: null, history: [] },
      },
    });
    renderApp('/drivers/new?driver=7&step=3', { user: staffUser });
    const last4 = await screen.findByLabelText('Last 4 digits on the document');
    expect(last4).toHaveAttribute('maxLength', '4');
    await userEvent.type(last4, '12a');
    await userEvent.type(
      screen.getByLabelText('Date or year of birth (YYYY or YYYY-MM-DD)'),
      '1990',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Save details' }));
    expect(await screen.findByText('Enter exactly 4 digits.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/drivers/7/kyc/identity/attempts')).toHaveLength(0);
    const uploads = screen.getAllByRole('group');
    expect(
      within(uploads[0] as HTMLElement).getByRole('button', { name: /Take photo/ }),
    ).toBeVisible();
  });
});
