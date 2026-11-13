import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import { CaptureInput } from '../../components/CaptureInput';
import { SecureImage } from '../../components/SecureDocument';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Loading } from '../../components/ui/Loading';
import { Select } from '../../components/ui/Select';
import { useToast } from '../../components/ui/useToast';
import { formatDateTime } from '../../lib/format';
import { errorMessage } from '../../lib/errors';
import { strings } from '../../lib/strings';
import { DecisionPanel, EligibilityPanel, KycCheckEditor, StatusBadge } from '../kyc/components';
import { fetchDriverKyc, recordConsent, type CheckType } from '../kyc/api';
import { fetchDriver, uploadDriverPhoto, type Driver } from './api';
import { DriverDetailsForm } from './DriverDetailsForm';

const w = strings.wizard;
const STEPS = w.steps;

/**
 * Register driver wizard: details, photo, consent, identity (manual), licence (manual), review
 * and decision. Every step saves to the server at once (the driver record and its KYC attempts
 * are the draft), and the URL keeps the driver and step, so it can be resumed any time.
 */
export default function RegisterDriverPage() {
  const [params, setParams] = useSearchParams();
  const driverId = Number(params.get('driver') ?? '') || null;
  const requested = Number(params.get('step') ?? '');
  const step = driverId === null ? 0 : Number.isInteger(requested) && requested > 0 ? requested : 1;

  const driver = useQuery({
    queryKey: ['driver', driverId],
    queryFn: () => fetchDriver(driverId ?? 0),
    enabled: driverId !== null,
  });

  const go = (nextStep: number, id: number | null = driverId) => {
    const next = new URLSearchParams();
    if (id !== null) next.set('driver', String(id));
    next.set('step', String(nextStep));
    setParams(next);
    window.scrollTo?.({ top: 0 });
  };

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.registerDriver}</h1>
      <ol
        className="flex gap-1 overflow-x-auto text-xs"
        aria-label={w.stepOf(step + 1, STEPS.length)}
      >
        {STEPS.map((label, index) => {
          const reachable = index === 0 ? driverId === null : driverId !== null;
          const current = index === step;
          return (
            <li key={label}>
              <button
                type="button"
                disabled={!reachable || current}
                aria-current={current ? 'step' : undefined}
                onClick={() => go(index)}
                className={`rounded-full px-3 py-1 whitespace-nowrap ${
                  current
                    ? 'bg-teal-700 font-medium text-white'
                    : reachable
                      ? 'bg-white text-slate-700 hover:bg-slate-100'
                      : 'bg-slate-100 text-slate-400'
                }`}
              >
                {index + 1}. {label}
              </button>
            </li>
          );
        })}
      </ol>
      <p className="text-sm text-slate-600">{w.stepOf(step + 1, STEPS.length)}</p>

      {step === 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <DriverDetailsForm
            driver={null}
            submitLabel={w.saveAndContinue}
            onSaved={(created) => go(1, created.id)}
          />
        </div>
      )}
      {step > 0 && driver.isPending && <Loading />}
      {step > 0 && driver.isError && <Alert>{errorMessage(driver.error)}</Alert>}
      {step > 0 && driver.data && <WizardStep step={step} driver={driver.data} go={(n) => go(n)} />}
    </section>
  );
}

function WizardStep({
  step,
  driver,
  go,
}: {
  step: number;
  driver: Driver;
  go: (step: number) => void;
}) {
  const queryClient = useQueryClient();
  const kyc = useQuery({
    queryKey: ['driver-kyc', driver.id],
    queryFn: () => fetchDriverKyc(driver.id),
    enabled: driver.can_view_kyc && step >= 2,
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['driver', driver.id] }),
      queryClient.invalidateQueries({ queryKey: ['driver-kyc', driver.id] }),
      queryClient.invalidateQueries({ queryKey: ['eligibility', driver.id] }),
    ]);

  const nav = (
    <div className="flex justify-between gap-2">
      <Button variant="secondary" onClick={() => go(step - 1)} disabled={step <= 1}>
        {w.back}
      </Button>
      {step < STEPS.length - 1 && <Button onClick={() => go(step + 1)}>{w.continue}</Button>}
    </div>
  );

  if (step === 1) {
    return (
      <div className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-4">
        <p className="text-sm text-slate-700">
          {driver.code} · {driver.full_name}
        </p>
        <h2 className="text-lg font-semibold text-slate-900">{w.photoTitle}</h2>
        <PhotoStep driver={driver} onSaved={refresh} />
        {nav}
      </div>
    );
  }

  if (!driver.can_view_kyc) return <Alert tone="info">{strings.drivers.kycHidden}</Alert>;
  if (kyc.isPending) return <Loading />;
  if (kyc.isError) return <Alert>{errorMessage(kyc.error)}</Alert>;
  const data = kyc.data;

  if (step === 2) {
    return (
      <div className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-lg font-semibold text-slate-900">{w.consentTitle}</h2>
        <ConsentStep
          driverId={driver.id}
          recordedAt={data.consents.find((c) => !c.withdrawn_at)?.captured_at ?? null}
          onSaved={refresh}
        />
        {nav}
      </div>
    );
  }

  if (step === 3 || step === 4) {
    const checkType: CheckType = step === 3 ? 'identity' : 'licence';
    return (
      <div className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-lg font-semibold text-slate-900">
          {checkType === 'identity' ? w.identityTitle : w.licenceTitle}
        </h2>
        {data.has_kyc_consent ? (
          <KycCheckEditor
            key={`${checkType}-${data[checkType]?.id ?? 'new'}`}
            driverId={driver.id}
            checkType={checkType}
            attempt={data[checkType]}
            acceptedIdTypes={data.accepted_id_types}
            methods={data.available_methods[checkType]}
            defaultName={driver.full_name}
            onChanged={refresh}
          />
        ) : (
          <Alert>{w.consentRequired}</Alert>
        )}
        {nav}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-lg font-semibold text-slate-900">{w.reviewTitle}</h2>
        <EligibilityPanel driverId={driver.id} />
      </div>
      {(['identity', 'licence'] as const).map((checkType) => {
        const attempt = data[checkType];
        return (
          <div
            key={checkType}
            className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4"
          >
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold text-slate-900">{strings.kyc.checkLabels[checkType]}</h3>
              <StatusBadge status={attempt?.status ?? null} />
            </div>
            {attempt ? (
              <>
                <Link
                  to={`/kyc/attempts/${attempt.id}`}
                  className="text-sm text-teal-800 underline"
                >
                  {strings.drivers.review}
                </Link>
                <DecisionPanel
                  attempt={attempt}
                  canDecide={driver.can_reveal}
                  onChanged={refresh}
                />
              </>
            ) : (
              <Button variant="secondary" onClick={() => go(checkType === 'identity' ? 3 : 4)}>
                {strings.drivers.continueOnboarding}
              </Button>
            )}
          </div>
        );
      })}
      <div className="flex justify-between gap-2">
        <Button variant="secondary" onClick={() => go(step - 1)}>
          {w.back}
        </Button>
        <Link
          to={`/drivers/${driver.id}`}
          className="inline-flex min-h-10 items-center rounded-md bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800"
        >
          {w.finish}
        </Link>
      </div>
    </div>
  );
}

function PhotoStep({ driver, onSaved }: { driver: Driver; onSaved: () => Promise<unknown> }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const upload = async (file: Blob, name: string) => {
    setBusy(true);
    setError(null);
    try {
      await uploadDriverPhoto(driver.id, file, name);
      toast.show({ message: w.photoDone, tone: 'success' });
      await onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-3">
      {error && <Alert>{error}</Alert>}
      {driver.photo_document_id && (
        <SecureImage
          key={driver.photo_document_id}
          documentId={driver.photo_document_id}
          label={strings.documents.labels.driver_photo ?? 'Driver photo'}
          className="max-h-64 w-auto self-start"
        />
      )}
      <CaptureInput
        label={w.photoTitle}
        busy={busy}
        done={driver.photo_document_id !== null}
        hint={strings.capture.photoHint}
        onFile={(file, name) => void upload(file, name)}
      />
    </div>
  );
}

function ConsentStep({
  driverId,
  recordedAt,
  onSaved,
}: {
  driverId: number;
  recordedAt: string | null;
  onSaved: () => Promise<unknown>;
}) {
  const [method, setMethod] = useState<'in_person_checkbox' | 'in_person_signed'>(
    'in_person_checkbox',
  );
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (recordedAt) {
    return <Alert tone="success">{w.consentRecorded(formatDateTime(recordedAt))}</Alert>;
  }

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await recordConsent(driverId, method);
      await onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-800">{w.consentNotice}</p>
      <Select
        label={w.consentMethod}
        value={method}
        options={[
          { value: 'in_person_checkbox', label: w.consentCheckbox },
          { value: 'in_person_signed', label: w.consentSigned },
        ]}
        onChange={(event) => setMethod(event.target.value as typeof method)}
      />
      <label className="flex items-start gap-2 text-sm text-slate-800">
        <input
          type="checkbox"
          className="mt-0.5 size-4 accent-teal-700"
          checked={agreed}
          onChange={(event) => setAgreed(event.target.checked)}
        />
        {w.consentConfirm}
      </label>
      {error && <Alert>{error}</Alert>}
      <div>
        <Button onClick={save} disabled={!agreed} loading={busy}>
          {w.recordConsent}
        </Button>
      </div>
    </div>
  );
}
