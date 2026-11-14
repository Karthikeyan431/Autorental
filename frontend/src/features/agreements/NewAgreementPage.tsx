import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { useToast } from '../../components/ui/useToast';
import { businessToday } from '../../lib/dates';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatRupees } from '../../lib/format';
import { parseRupeesToPaise } from '../../lib/money';
import { strings } from '../../lib/strings';
import { listVehicles } from '../autos/api';
import { fetchDriver, listDrivers } from '../drivers/api';
import { activateAgreement, createAgreement, fetchEligibility } from './api';
import { EligibilityPanel } from './components';

const t = strings.agreements;

/** New agreement (requirements §4.9): pick an eligible driver and an available auto, see every
 * reason live, set the rate and start date, confirm. Activation checks everything again. */
export default function NewAgreementPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const preset = Number(params.get('driver')) || null;

  const [driverSearch, setDriverSearch] = useState('');
  const [driverId, setDriverId] = useState<number | null>(preset);
  const [vehicleId, setVehicleId] = useState<number | null>(null);
  const [startDate, setStartDate] = useState(businessToday());
  const [rent, setRent] = useState('');
  const [advance, setAdvance] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<'activate' | 'draft' | null>(null);

  const drivers = useQuery({
    queryKey: ['drivers', 'agreement-picker', driverSearch],
    queryFn: () =>
      listDrivers({ page: 1, search: driverSearch, status: 'active', managedBy: '', kyc: '' }),
  });
  const presetDriver = useQuery({
    queryKey: ['driver', preset],
    queryFn: () => fetchDriver(preset ?? 0),
    enabled: preset !== null,
  });
  const vehicles = useQuery({
    queryKey: ['vehicles', 'available-picker'],
    queryFn: () => listVehicles({ page: 1, search: '', status: 'available' }),
  });
  const ready = driverId !== null && vehicleId !== null && Boolean(startDate);
  const eligibility = useQuery({
    queryKey: ['agreement-eligibility', driverId, vehicleId, startDate],
    queryFn: () => fetchEligibility(driverId ?? 0, vehicleId ?? 0, startDate),
    enabled: ready,
  });

  const driverOptions = [...(drivers.data?.items ?? [])];
  if (presetDriver.data && !driverOptions.some((d) => d.id === presetDriver.data.id)) {
    driverOptions.unshift(presetDriver.data);
  }
  const driver = driverOptions.find((d) => d.id === driverId);
  const vehicle = vehicles.data?.items.find((v) => v.id === vehicleId);

  const values = () => {
    const rentPaise = parseRupeesToPaise(rent);
    const advancePaise = advance.trim() ? parseRupeesToPaise(advance) : 0;
    if (!ready) return { error: t.required };
    if (rentPaise === null || rentPaise <= 0) return { error: t.rentInvalid };
    if (advancePaise === null) return { error: t.advanceInvalid };
    return {
      input: {
        driver_id: driverId,
        vehicle_id: vehicleId,
        start_date: startDate,
        daily_rent_paise: rentPaise,
        advance_required_paise: advancePaise,
      },
    };
  };

  const review = (event: FormEvent) => {
    event.preventDefault();
    const checked = values();
    setError(checked.error ?? null);
    if (checked.input) setConfirming(true);
  };

  const save = async (activate: boolean) => {
    const checked = values();
    if (!checked.input) return;
    setBusy(activate ? 'activate' : 'draft');
    setError(null);
    try {
      const draft = await createAgreement(checked.input);
      if (activate) {
        try {
          await activateAgreement(draft.id);
          toast.show({ message: t.activated, tone: 'success' });
        } catch (e) {
          // The draft is kept; its page shows why it could not start.
          toast.show({ message: errorMessage(e), tone: 'error' });
        }
      } else {
        toast.show({ message: t.draftSaved, tone: 'success' });
      }
      await queryClient.invalidateQueries({ queryKey: ['agreements'] });
      await queryClient.invalidateQueries({ queryKey: ['vehicles'] });
      await queryClient.invalidateQueries({ queryKey: ['vehicle-summary'] });
      void navigate(`/agreements/${draft.id}`);
    } catch (e) {
      setConfirming(false);
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.newAgreement}</h1>
      <form
        noValidate
        onSubmit={review}
        className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2"
      >
        <Input
          label={t.driverSearch}
          value={driverSearch}
          onChange={(event) => setDriverSearch(event.target.value)}
        />
        <Select
          label={t.pickDriver}
          value={driverId === null ? '' : String(driverId)}
          options={[
            { value: '', label: t.pickDriverPlaceholder },
            ...driverOptions.map((d) => ({
              value: String(d.id),
              label: `${d.full_name} (${d.code})`,
            })),
          ]}
          onChange={(event) => setDriverId(event.target.value ? Number(event.target.value) : null)}
        />
        <Select
          label={t.pickAuto}
          value={vehicleId === null ? '' : String(vehicleId)}
          options={[
            { value: '', label: t.pickAutoPlaceholder },
            ...(vehicles.data?.items ?? []).map((v) => ({
              value: String(v.id),
              label: `${v.registration_number} · ${v.make} ${v.model}`,
            })),
          ]}
          onChange={(event) => setVehicleId(event.target.value ? Number(event.target.value) : null)}
        />
        <Input
          label={t.startDate}
          type="date"
          value={startDate}
          max={businessToday()}
          onChange={(event) => setStartDate(event.target.value)}
        />
        <Input
          label={t.dailyRentLabel}
          inputMode="decimal"
          value={rent}
          onChange={(event) => setRent(event.target.value)}
        />
        <Input
          label={t.advanceLabel}
          inputMode="decimal"
          value={advance}
          onChange={(event) => setAdvance(event.target.value)}
        />
        {vehicles.data && vehicles.data.items.length === 0 && (
          <p className="text-sm text-amber-900 sm:col-span-2">{t.noAutos}</p>
        )}
        <div className="sm:col-span-2">
          <EligibilityPanel
            ready={ready}
            checking={eligibility.isFetching}
            eligibility={eligibility.data}
          />
        </div>
        <p className="text-xs text-slate-600 sm:col-span-2">
          {t.rateFixed} {t.backdateNote(eligibility.data?.max_backdate_days ?? 7)}
        </p>
        {error && (
          <div className="sm:col-span-2">
            <Alert>{error}</Alert>
          </div>
        )}
        <div className="flex justify-end sm:col-span-2">
          <Button type="submit">{t.review}</Button>
        </div>
      </form>

      {confirming && driver && vehicle && (
        <Dialog open title={t.confirmTitle} onClose={() => setConfirming(false)}>
          <div className="flex flex-col gap-3">
            <p className="text-sm text-slate-700">
              {t.confirmBody(
                `${driver.full_name} (${driver.code})`,
                vehicle.registration_number,
                formatRupees(parseRupeesToPaise(rent) ?? 0),
                formatDate(startDate),
              )}
            </p>
            {eligibility.data && !eligibility.data.ok && (
              <EligibilityPanel ready checking={false} eligibility={eligibility.data} />
            )}
            <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
              <Button
                variant="secondary"
                loading={busy === 'draft'}
                disabled={busy !== null}
                onClick={() => void save(false)}
              >
                {t.saveDraft}
              </Button>
              <Button
                loading={busy === 'activate'}
                disabled={busy !== null || !eligibility.data?.ok}
                onClick={() => void save(true)}
              >
                {t.confirm}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </section>
  );
}
