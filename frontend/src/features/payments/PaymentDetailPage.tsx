import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import { SecureDocument } from '../../components/SecureDocument';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { useToast } from '../../components/ui/useToast';
import { ApiError } from '../../lib/api';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatDateTime, formatRupees } from '../../lib/format';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import {
  applyCredit,
  confirmDays,
  fetchPayment,
  fetchReceiptPdf,
  fetchSuggestion,
  requestReversal,
  type Payment,
} from './api';
import { ConfirmDays, PaymentStatusBadge } from './components';

const t = strings.payments;
const d = t.detail;

/** One payment: its days (rule 4), the receipt (rule 13) and a reversal request (Q4). */
export default function PaymentDetailPage() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [reversalOpen, setReversalOpen] = useState(false);
  const payment = useQuery({ queryKey: ['payment', id], queryFn: () => fetchPayment(id) });

  if (payment.isPending) return <Loading />;
  if (payment.isError)
    return (
      <ErrorState
        requestId={payment.error instanceof ApiError ? payment.error.requestId : null}
        onRetry={() => void payment.refetch()}
      />
    );
  const p = payment.data;

  const save =
    (credit: boolean) => async (items: { rent_charge_id: number; amount_paise: number }[]) => {
      const updated = credit ? await applyCredit(p.id, items) : await confirmDays(p.id, items);
      queryClient.setQueryData(['payment', id], updated);
      await queryClient.invalidateQueries({ queryKey: ['payments'] });
      toast.show({ message: t.confirm.saved, tone: 'success' });
    };

  const download = async () => {
    try {
      const blob = await fetchReceiptPdf(p.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${(p.receipt_no ?? 'receipt').replaceAll('/', '-')}.pdf`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) {
      toast.show({ message: errorMessage(caught), tone: 'error' });
    }
  };

  const showDays =
    p.purpose === 'rent' &&
    p.can_confirm_days &&
    (p.status === 'awaiting_approval' || p.unallocated_paise > 0);

  return (
    <section className="flex flex-col gap-4">
      <Link to="/payments" className="text-sm text-teal-800 underline">
        {d.back}
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">{d.title(p.id)}</h1>
        <PaymentStatusBadge payment={p} />
      </div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-lg border border-slate-200 bg-white p-4 text-sm sm:grid-cols-2">
        <Row label={d.driver}>
          <Link to={`/drivers/${p.driver.id}`} className="text-teal-800 underline">
            {p.driver.full_name} ({p.driver.code})
          </Link>
        </Row>
        <Row label={d.amount}>
          <span className="tabular-nums">{formatRupees(p.amount_paise)}</span>
          {p.purpose === 'advance_deposit' && ` · ${t.record.purposes.advance_deposit}`}
        </Row>
        <Row label={d.method}>{t.record.methods[p.method] ?? p.method}</Row>
        <Row label={d.reference}>{p.reference ?? '—'}</Row>
        <Row label={d.receivedOn}>{formatDate(p.received_on)}</Row>
        <Row label={d.recordedBy}>
          {p.recorded_by.name}, {formatDateTime(p.recorded_at)}
        </Row>
        {p.receipt_no && (
          <Row label={d.receipt}>
            {p.receipt_no}
            {p.receipt_cancelled && ` (${d.receiptCancelled})`}
          </Row>
        )}
        {p.unallocated_paise > 0 && p.purpose === 'rent' && (
          <Row label={d.unallocated}>
            <span className="tabular-nums">{formatRupees(p.unallocated_paise)}</span>
          </Row>
        )}
        {p.rejection_reason && <Row label={d.rejection}>{p.rejection_reason}</Row>}
      </dl>
      <div className="flex flex-wrap gap-2">
        {p.receipt_no && (
          <Button variant="secondary" onClick={() => void download()}>
            {d.downloadReceipt}
          </Button>
        )}
        {p.status === 'approved' &&
          can(user, 'adjustments.request') &&
          (p.pending_reversal_id ? (
            <Alert tone="info">{d.reversalWaiting}</Alert>
          ) : (
            <Button variant="ghost" onClick={() => setReversalOpen(true)}>
              {d.requestReversal}
            </Button>
          ))}
      </div>
      {p.proof_document_id && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-lg font-semibold">{d.proof}</h2>
          <SecureDocument
            documentId={p.proof_document_id}
            mimeType="image/jpeg"
            label={d.openProof}
          />
        </div>
      )}
      {p.purpose === 'rent' && <DaysCovered payment={p} />}
      {showDays && (
        <ConfirmDays
          payment={p}
          fetchSuggestionFor={fetchSuggestion}
          save={save(p.status === 'approved')}
        />
      )}
      {reversalOpen && <ReversalDialog payment={p} onClose={() => setReversalOpen(false)} />}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-900">{children}</dd>
    </div>
  );
}

function DaysCovered({ payment }: { payment: Payment }) {
  const live = payment.status === 'awaiting_approval' || payment.status === 'approved';
  const rows = live
    ? payment.allocations.filter((a) => a.reversed_at === null)
    : payment.allocations;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
      <h2 className="mb-2 text-lg font-semibold">{d.days}</h2>
      {!payment.can_confirm_days && payment.allocations.length === 0 ? (
        <p className="text-slate-600">{d.daysHidden}</p>
      ) : rows.length === 0 ? (
        <p className="text-slate-600">{d.noDays}</p>
      ) : (
        <ul className="flex flex-col gap-1" aria-label={d.days}>
          {rows.map((a) => (
            <li key={a.id} className={a.reversed_at ? 'text-slate-500' : ''}>
              {formatDate(a.rent_date)} ·{' '}
              <span className="tabular-nums">{formatRupees(a.amount_paise)}</span>
              {a.reversal_reason && ` (${a.reversal_reason})`}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReversalDialog({ payment, onClose }: { payment: Payment; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await requestReversal(payment.id, reason.trim());
      toast.show({ message: d.reversalSent, tone: 'success' });
      await queryClient.invalidateQueries({ queryKey: ['payment', payment.id] });
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open
      title={d.requestReversal}
      onClose={onClose}
      footer={
        <Button onClick={() => void submit()} loading={busy} disabled={reason.trim().length < 3}>
          {d.requestReversal}
        </Button>
      }
    >
      {error && <Alert>{error}</Alert>}
      <Input
        label={d.reversalReason}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
    </Dialog>
  );
}
