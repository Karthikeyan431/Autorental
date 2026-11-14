import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router';

import { CaptureInput } from '../../components/CaptureInput';
import { SecureDocument } from '../../components/SecureDocument';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { useToast } from '../../components/ui/useToast';
import { containsAadhaarLike, NO_FULL_NUMBER_MESSAGE } from '../../lib/aadhaar';
import { ApiError } from '../../lib/api';
import { businessToday } from '../../lib/dates';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatDateTime, formatRupees } from '../../lib/format';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import {
  activateAgreement,
  cancelAgreement,
  endAgreement,
  fetchAgreement,
  fetchAgreementPdf,
  uploadSignedCopy,
  type Agreement,
} from './api';
import { AgreementStatusBadge } from './components';

const t = strings.agreements;

/** One agreement: details, print, signed copy, activate, end or cancel (requirements §4.9). */
export default function AgreementDetailPage() {
  const id = Number(useParams().id);
  const query = useQuery({ queryKey: ['agreement', id], queryFn: () => fetchAgreement(id) });

  if (query.isPending) return <Loading />;
  if (query.isError) {
    return (
      <ErrorState
        requestId={query.error instanceof ApiError ? query.error.requestId : null}
        onRetry={() => void query.refetch()}
      />
    );
  }
  return <AgreementView agreement={query.data} />;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-100 py-1 text-sm">
      <dt className="text-slate-600">{label}</dt>
      <dd className="text-right text-slate-900">{value || '—'}</dd>
    </div>
  );
}

function who(ref: { name: string } | null, at: string | null): string | null {
  if (!ref) return null;
  return at ? `${ref.name}, ${formatDateTime(at)}` : ref.name;
}

function useRefresh(id: number) {
  const queryClient = useQueryClient();
  return async () => {
    for (const key of ['agreement', 'agreements', 'vehicles', 'vehicle-summary', 'rent-summary']) {
      await queryClient.invalidateQueries({ queryKey: key === 'agreement' ? [key, id] : [key] });
    }
  };
}

function AgreementView({ agreement: a }: { agreement: Agreement }) {
  const { user } = useAuth();
  const toast = useToast();
  const refresh = useRefresh(a.id);
  const manage = can(user, 'agreements.manage');
  const [ending, setEnding] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (key: string, action: () => Promise<unknown>, success: string) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      toast.show({ message: success, tone: 'success' });
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const print = async () => {
    setBusy('print');
    setError(null);
    try {
      const blob = await fetchAgreementPdf(a.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `agreement-${a.agreement_no}.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError(t.printFailed);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">
          {strings.pages.agreement} {a.agreement_no}
        </h1>
        <AgreementStatusBadge status={a.status} />
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <dl>
          <Row
            label={t.driver}
            value={
              <Link to={`/drivers/${a.driver.id}`} className="text-teal-800 underline">
                {a.driver.full_name} ({a.driver.code})
              </Link>
            }
          />
          <Row
            label={t.auto}
            value={
              <Link to={`/autos/${a.vehicle.id}`} className="text-teal-800 underline">
                {a.vehicle.registration_number} · {a.vehicle.make} {a.vehicle.model}
              </Link>
            }
          />
          <Row label={t.dailyRent} value={formatRupees(a.daily_rent_paise)} />
          <Row label={t.advance} value={formatRupees(a.advance_required_paise)} />
          <Row label={t.startDate} value={formatDate(a.start_date)} />
          <Row label={t.endDate} value={a.end_date ? formatDate(a.end_date) : null} />
          {a.vehicle_available_from && (
            <Row label={t.auto} value={t.availableFrom(formatDate(a.vehicle_available_from))} />
          )}
          <Row label={t.createdBy} value={who(a.created_by, a.created_at)} />
          <Row label={t.activatedBy} value={who(a.activated_by, a.activated_at)} />
          {a.ended_by && <Row label={t.endedBy} value={who(a.ended_by, a.ended_at)} />}
          {a.end_reason && <Row label={t.endReason} value={a.end_reason} />}
          {a.cancelled_by && (
            <Row label={t.cancelledBy} value={who(a.cancelled_by, a.cancelled_at)} />
          )}
          {a.cancel_reason && <Row label={t.cancelReason} value={a.cancel_reason} />}
          <Row label={t.terms} value={t.termsPlaceholder} />
        </dl>
      </div>

      {error && <Alert>{error}</Alert>}
      {manage && (
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <Button variant="secondary" loading={busy === 'print'} onClick={() => void print()}>
            {t.print}
          </Button>
          {a.status === 'draft' && (
            <>
              <Button
                loading={busy === 'activate'}
                onClick={() => void run('activate', () => activateAgreement(a.id), t.activated)}
              >
                {t.activate}
              </Button>
              <Button variant="secondary" onClick={() => setCancelling(true)}>
                {t.cancelDraft}
              </Button>
            </>
          )}
          {a.status === 'active' && <Button onClick={() => setEnding(true)}>{t.end}</Button>}
        </div>
      )}

      {a.status !== 'cancelled' && <SignedCopy agreement={a} manage={manage} />}
      {ending && <EndDialog agreement={a} onClose={() => setEnding(false)} onDone={refresh} />}
      {cancelling && (
        <CancelDialog agreement={a} onClose={() => setCancelling(false)} onDone={refresh} />
      )}
    </section>
  );
}

function SignedCopy({ agreement: a, manage }: { agreement: Agreement; manage: boolean }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const upload = async (blob: Blob, name: string) => {
    setBusy(true);
    setError(null);
    try {
      await uploadSignedCopy(a.id, blob, name);
      toast.show({ message: t.signedUploaded, tone: 'success' });
      await queryClient.invalidateQueries({ queryKey: ['agreement', a.id] });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="text-sm font-semibold text-slate-900">{t.signedCopy}</h2>
      {a.signed_document_id ? (
        <SecureDocument
          documentId={a.signed_document_id}
          mimeType="application/pdf"
          label={`${t.signedCopy} ${a.agreement_no}`}
        />
      ) : (
        <p className="text-sm text-slate-600">{t.signedCopyNone}</p>
      )}
      {manage && (
        <CaptureInput
          label={t.uploadSigned}
          allowPdf
          busy={busy}
          done={a.signed_document_id !== null}
          onFile={(blob, name) => void upload(blob, name)}
        />
      )}
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

function EndDialog({
  agreement: a,
  onClose,
  onDone,
}: {
  agreement: Agreement;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const toast = useToast();
  const today = businessToday();
  const [endDate, setEndDate] = useState(today);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (containsAadhaarLike(reason)) {
      setError(NO_FULL_NUMBER_MESSAGE);
      return;
    }
    setBusy(true);
    try {
      const result = await endAgreement(a.id, endDate, reason.trim() || null);
      toast.show({
        message: result.waivers_created ? t.endedWithWaivers(result.waivers_created) : t.ended,
        tone: 'success',
      });
      await onDone();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={t.endTitle} onClose={onClose}>
      <form noValidate className="flex flex-col gap-3" onSubmit={(event) => void submit(event)}>
        <p className="text-sm text-slate-700">{t.endHelp}</p>
        <Input
          label={t.endDate}
          type="date"
          value={endDate}
          min={a.start_date}
          max={today}
          onChange={(event) => setEndDate(event.target.value)}
        />
        <Input
          label={t.endReason}
          value={reason}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
        />
        {error && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t.cancel}
          </Button>
          <Button type="submit" loading={busy}>
            {t.end}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function CancelDialog({
  agreement: a,
  onClose,
  onDone,
}: {
  agreement: Agreement;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!reason.trim()) {
      setError(t.reasonRequired);
      return;
    }
    if (containsAadhaarLike(reason)) {
      setError(NO_FULL_NUMBER_MESSAGE);
      return;
    }
    setBusy(true);
    try {
      await cancelAgreement(a.id, reason.trim());
      toast.show({ message: t.cancelled, tone: 'success' });
      await onDone();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={t.cancelTitle} onClose={onClose}>
      <form noValidate className="flex flex-col gap-3" onSubmit={(event) => void submit(event)}>
        <Input
          label={t.cancelReason}
          value={reason}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
        />
        {error && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t.cancel}
          </Button>
          <Button type="submit" loading={busy}>
            {t.cancelDraft}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
