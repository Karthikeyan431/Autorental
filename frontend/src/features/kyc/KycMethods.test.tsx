import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { driver, driverKyc, identityAttempt } from '../../test/drivers';
import { callsTo, mockApi } from '../../test/mock-api';
import { renderApp } from '../../test/render';
import { staffUser } from '../../test/users';
import type { Attempt, DriverKyc } from './api';

/** KYC methods in the wizard (rule 8; D47, D48, D49): the server lists the methods a new
 * attempt may use; attestation appears only with its flag on; the Parivahan record opens the
 * official site in a new tab; a demo check always shows "DEMO – not real". */

afterEach(() => {
  vi.unstubAllGlobals();
});

const newAttempt = (overrides: Partial<Attempt>): Attempt => ({
  ...identityAttempt,
  id: 40,
  status: 'draft',
  identity_details: null,
  documents: [],
  events: [],
  ...overrides,
});

function kyc(overrides: Partial<DriverKyc>): DriverKyc {
  return { ...driverKyc, identity: null, licence: null, history: [], ...overrides };
}

describe('KYC methods', () => {
  it('offers only manual review for identity while the attestation flag is off', async () => {
    mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/kyc': { body: kyc({}) },
    });
    renderApp('/drivers/new?driver=7&step=3', { user: staffUser });
    expect(await screen.findByLabelText('Last 4 digits on the document')).toBeInTheDocument();
    expect(screen.queryByLabelText('How will you check this?')).not.toBeInTheDocument();
    expect(screen.queryByText(/UIDAI app/)).not.toBeInTheDocument();
  });

  it('records a UIDAI app attestation when the server offers it', async () => {
    const attested = newAttempt({
      method: 'uidai_app_attested',
      method_label: 'Checked by staff with the UIDAI app',
      checklist: [],
      required_documents: [],
    });
    const fetchMock = mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/kyc': {
        body: kyc({
          available_methods: {
            identity: ['manual', 'uidai_app_attested'],
            licence: ['manual', 'parivahan_lookup'],
          },
        }),
      },
      'POST /api/v1/drivers/7/kyc/identity/attempts': { status: 201, body: attested },
      'POST /api/v1/kyc/attempts/40/uidai-app-attestation': { body: attested },
    });
    const user = userEvent.setup();
    renderApp('/drivers/new?driver=7&step=3', { user: staffUser });
    await user.selectOptions(
      await screen.findByLabelText('How will you check this?'),
      'uidai_app_attested',
    );
    await user.type(screen.getByLabelText('Date or year of birth (YYYY or YYYY-MM-DD)'), '1990');
    await user.type(screen.getByLabelText('Last 4 digits on the document'), '0007');
    await user.selectOptions(
      screen.getByLabelText('The UIDAI app showed the signature as valid'),
      'no',
    );
    await user.click(screen.getByRole('button', { name: 'Save details' }));

    expect(await screen.findByText('Details saved.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/drivers/7/kyc/identity/attempts')[0]?.body).toEqual({
      method: 'uidai_app_attested',
    });
    expect(
      callsTo(fetchMock, 'POST', '/api/v1/kyc/attempts/40/uidai-app-attestation')[0]?.body,
    ).toEqual({
      name_on_document: 'Test Driver 007',
      id_last4: '0007',
      dob_or_yob: '1990',
      signature_valid: false,
    });
  });

  it('records a Parivahan lookup, opening the official site in a new tab', async () => {
    const lookup = newAttempt({
      check_type: 'licence',
      method: 'parivahan_lookup',
      method_label: 'Looked up by staff on the Parivahan site',
      required_documents: ['lookup_screenshot'],
    });
    const fetchMock = mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/kyc': { body: kyc({}) },
      'POST /api/v1/drivers/7/kyc/licence/attempts': { status: 201, body: lookup },
      'POST /api/v1/kyc/attempts/40/parivahan-lookup': { body: lookup },
    });
    const user = userEvent.setup();
    renderApp('/drivers/new?driver=7&step=4', { user: staffUser });
    await user.selectOptions(
      await screen.findByLabelText('How will you check this?'),
      'parivahan_lookup',
    );
    const open = screen.getByRole('link', { name: 'Open Parivahan' });
    expect(open).toHaveAttribute('href', 'https://parivahan.gov.in/rcdlstatus/?pur_cd=101');
    expect(open).toHaveAttribute('target', '_blank');
    expect(open).toHaveAttribute('rel', 'noopener noreferrer');
    expect(
      screen.getByRole('button', { name: 'Take photo: Parivahan screenshot (required)' }),
    ).toBeVisible();

    await user.type(screen.getByLabelText('Licence number'), 'TEST-DL-0007');
    await user.type(screen.getByLabelText('Valid until (non-transport)'), '2036-01-01');
    await user.type(screen.getByLabelText('Vehicle classes (comma separated)'), '3W-TEST');
    await user.type(screen.getByLabelText('Status shown on Parivahan'), 'ACTIVE (DEMO)');
    await user.click(screen.getByRole('button', { name: 'Save details' }));

    expect(await screen.findByText('Details saved.')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/v1/drivers/7/kyc/licence/attempts')[0]?.body).toEqual({
      method: 'parivahan_lookup',
    });
    const body = callsTo(fetchMock, 'POST', '/api/v1/kyc/attempts/40/parivahan-lookup')[0]
      ?.body as Record<string, unknown>;
    expect(body.lookup_status_text).toBe('ACTIVE (DEMO)');
    expect(typeof body.looked_up_at).toBe('string');
    expect(body.licence_number).toBe('TEST-DL-0007');
  });

  it('marks a demo check "DEMO – not real"', async () => {
    const demo = newAttempt({
      method: 'demo',
      method_label: 'DEMO – not real',
      is_simulated: true,
      required_documents: [],
    });
    mockApi({
      'GET /api/v1/drivers/7': { body: driver },
      'GET /api/v1/drivers/7/kyc': { body: kyc({ identity: demo, history: [demo] }) },
    });
    renderApp('/drivers/new?driver=7&step=3', { user: staffUser });
    expect((await screen.findAllByTestId('demo-badge')).length).toBeGreaterThan(0);
    expect(screen.getByText(/A person still decides/)).toBeInTheDocument();
    // No uploads for the demo method.
    expect(screen.queryByRole('button', { name: /Take photo/ })).not.toBeInTheDocument();
  });
});
