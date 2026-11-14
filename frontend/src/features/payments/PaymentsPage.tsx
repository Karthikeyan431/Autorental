import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { Select } from '../../components/ui/Select';
import { Table, type Column } from '../../components/ui/Table';
import { useToast } from '../../components/ui/useToast';
import { ApiError } from '../../lib/api';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatDateTime, formatRupees } from '../../lib/format';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import {
  approvePayments,
  decideAdvance,
  decideReversal,
  fetchPendingAdvance,
  fetchReversalRequests,
  listPayments,
  rejectPayment,
  type ApprovalResult,
  type Payment,
  type PaymentFilters,
  type PaymentStatus,
} from './api';
import { PaymentStatusBadge } from './components';
import { RecordPaymentForm } from './RecordPaymentForm';

const t = strings.payments;

type Tab = 'record' | 'queue' | 'all' | 'reversals' | 'advance';

/** Payments (requirements §4.11): record, the owner's approval queue, receipts, reversals. */
export default function PaymentsPage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const tabs: { key: Tab; label: string; show: boolean }[] = [
    { key: 'queue', label: t.tabs.queue, show: can(user, 'payments.approve') },
    { key: 'record', label: t.tabs.record, show: can(user, 'payments.record') },
    { key: 'all', label: t.tabs.all, show: true },
    { key: 'reversals', label: t.tabs.reversals, show: can(user, 'payments.reverse_decide') },
    { key: 'advance', label: t.tabs.advance, show: can(user, 'advance.decide') },
  ];
  const visible = tabs.filter((item) => item.show);
  const wanted = params.get('tab') as Tab | null;
  const [tab, setTab] = useState<Tab>(
    wanted && visible.some((item) => item.key === wanted) ? wanted : (visible[0]?.key ?? 'all'),
  );
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.payments}</h1>
      <div role="tablist" className="flex flex-wrap gap-2 border-b border-slate-200">
        {visible.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            onClick={() => setTab(item.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === item.key
                ? 'border-teal-700 text-teal-800'
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
      {tab === 'record' && <RecordPaymentForm initialDriverId={params.get('driver')} />}
      {tab === 'queue' && <ApprovalQueue />}
      {tab === 'all' && <AllPayments />}
      {tab === 'reversals' && <ReversalRequests />}
      {tab === 'advance' && <PendingAdvance />}
    </section>
  );
}

function ApprovalQueue() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<ApprovalResult[]>([]);
  const [rejecting, setRejecting] = useState<Payment | null>(null);
  const queue = useQuery({
    queryKey: ['payments', 'queue'],
    queryFn: () => listPayments({ page: 1, status: 'awaiting_approval' }),
  });
  const rows = queue.data?.items ?? [];

  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const approve = async () => {
    setBusy(true);
    try {
      const outcome = await approvePayments([...selected]);
      setResults(outcome.filter((r) => r.outcome === 'refused'));
      const approved = outcome.filter((r) => r.outcome === 'approved').length;
      if (approved > 0) toast.show({ message: t.queue.approved(approved), tone: 'success' });
      setSelected(new Set());
      await queryClient.invalidateQueries({ queryKey: ['payments'] });
      await queryClient.invalidateQueries({ queryKey: ['payments-summary'] });
    } catch (caught) {
      toast.show({ message: errorMessage(caught), tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const columns: Column<Payment>[] = [
    {
      key: 'select',
      header: t.queue.selectAll,
      render: (p) => (
        <input
          type="checkbox"
          aria-label={t.queue.select(p.id)}
          checked={selected.has(p.id)}
          onChange={() => toggle(p.id)}
          className="size-4"
        />
      ),
    },
    ...listColumns(),
    {
      key: 'days',
      header: t.detail.days,
      render: (p) =>
        p.days_confirmed ? (
          t.queue.daysConfirmed
        ) : (
          <span className="text-amber-800">{t.queue.daysWaiting}</span>
        ),
    },
    {
      key: 'reject',
      header: '',
      render: (p) => (
        <Button variant="ghost" onClick={() => setRejecting(p)}>
          {t.queue.reject}
        </Button>
      ),
    },
  ];

  if (queue.isPending) return <Loading />;
  if (queue.isError)
    return (
      <ErrorState
        requestId={queue.error instanceof ApiError ? queue.error.requestId : null}
        onRetry={() => void queue.refetch()}
      />
    );
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-slate-600">{t.queue.intro}</p>
      {results.map((r) => (
        <Alert key={r.payment_id}>
          {`#${r.payment_id} ${t.queue.refused}: ${r.message ?? r.code ?? ''}`}
        </Alert>
      ))}
      <div>
        <Button onClick={() => void approve()} loading={busy} disabled={selected.size === 0}>
          {t.queue.approveSelected(selected.size)}
        </Button>
      </div>
      <Table
        caption={t.tabs.queue}
        columns={columns}
        rows={rows}
        getRowKey={(p) => p.id}
        emptyMessage={t.queue.none}
      />
      {rejecting && <RejectDialog payment={rejecting} onClose={() => setRejecting(null)} />}
    </div>
  );
}

function RejectDialog({ payment, onClose }: { payment: Payment; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await rejectPayment(payment.id, reason.trim());
      toast.show({ message: t.queue.rejected, tone: 'success' });
      await queryClient.invalidateQueries({ queryKey: ['payments'] });
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
      title={t.queue.rejectTitle}
      onClose={onClose}
      footer={
        <Button
          variant="danger"
          onClick={() => void submit()}
          loading={busy}
          disabled={reason.trim().length < 3}
        >
          {t.queue.reject}
        </Button>
      }
    >
      <p className="mb-2">
        {payment.driver.full_name} · {formatRupees(payment.amount_paise)}
      </p>
      {error && <Alert>{error}</Alert>}
      <Input
        label={t.queue.rejectReason}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
    </Dialog>
  );
}

function listColumns(): Column<Payment>[] {
  return [
    {
      key: 'id',
      header: '#',
      render: (p) => (
        <Link to={`/payments/${p.id}`} className="font-medium text-teal-800 underline">
          {p.id}
        </Link>
      ),
    },
    { key: 'date', header: t.list.date, render: (p) => formatDate(p.received_on) },
    {
      key: 'driver',
      header: t.list.driver,
      render: (p) => `${p.driver.full_name} (${p.driver.code})`,
    },
    {
      key: 'amount',
      header: t.list.amount,
      align: 'right',
      render: (p) => formatRupees(p.amount_paise),
    },
    {
      key: 'method',
      header: t.list.method,
      render: (p) => t.record.methods[p.method] ?? p.method,
    },
    {
      key: 'recorded',
      header: t.list.recordedBy,
      render: (p) => `${p.recorded_by.name}, ${formatDateTime(p.recorded_at)}`,
    },
  ];
}

export function PaymentsTable({ driverId }: { driverId?: number }) {
  const [filters, setFilters] = useState<PaymentFilters>({ page: 1, status: '', driverId });
  const payments = useQuery({
    queryKey: ['payments', 'list', filters],
    queryFn: () => listPayments(filters),
    placeholderData: keepPreviousData,
  });
  const columns: Column<Payment>[] = [
    ...listColumns(),
    { key: 'status', header: t.list.status, render: (p) => <PaymentStatusBadge payment={p} /> },
    { key: 'receipt', header: t.list.receipt, render: (p) => p.receipt_no ?? '—' },
  ];
  return (
    <div className="flex flex-col gap-3">
      <div className="max-w-xs">
        <Select
          label={t.list.status}
          value={filters.status}
          options={[
            { value: '', label: t.list.allStatuses },
            ...(['awaiting_approval', 'approved', 'rejected', 'reversed'] as const).map(
              (value) => ({ value, label: t.statusLabels[value] ?? value }),
            ),
          ]}
          onChange={(event) =>
            setFilters((current) => ({
              ...current,
              status: event.target.value as PaymentStatus | '',
              page: 1,
            }))
          }
        />
      </div>
      {payments.isPending ? (
        <Loading />
      ) : payments.isError ? (
        <ErrorState
          requestId={payments.error instanceof ApiError ? payments.error.requestId : null}
          onRetry={() => void payments.refetch()}
        />
      ) : (
        <Table
          caption={t.tabs.all}
          columns={columns}
          rows={payments.data.items}
          getRowKey={(p) => p.id}
          emptyMessage={t.list.none}
          pagination={{
            page: payments.data.page,
            pageSize: payments.data.page_size,
            total: payments.data.total,
            onPageChange: (page) => setFilters((current) => ({ ...current, page })),
          }}
        />
      )}
    </div>
  );
}

function AllPayments() {
  return <PaymentsTable />;
}

function ReversalRequests() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const requests = useQuery({ queryKey: ['reversal-requests'], queryFn: fetchReversalRequests });
  const decide = async (id: number, decision: 'approved' | 'rejected') => {
    try {
      await decideReversal(id, decision, null);
      toast.show({ message: t.reversals.decided, tone: 'success' });
      await queryClient.invalidateQueries({ queryKey: ['reversal-requests'] });
      await queryClient.invalidateQueries({ queryKey: ['payments'] });
    } catch (caught) {
      toast.show({ message: errorMessage(caught), tone: 'error' });
    }
  };
  if (requests.isPending) return <Loading />;
  if (requests.isError) return <ErrorState onRetry={() => void requests.refetch()} />;
  if (requests.data.length === 0) return <EmptyState message={t.reversals.none} />;
  return (
    <ul className="flex flex-col gap-3">
      {requests.data.map((r) => (
        <li key={r.id} className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
          <p className="font-medium">
            <Link to={`/payments/${r.payment_id ?? ''}`} className="text-teal-800 underline">
              #{r.payment_id}
            </Link>{' '}
            {r.driver.full_name} · {formatRupees(r.amount_paise)} · {r.receipt_no}
          </p>
          <p>
            {t.reversals.reason}: {r.reason}
          </p>
          <p className="text-slate-600">
            {t.reversals.requestedBy}: {r.requested_by.name}, {formatDateTime(r.requested_at)}
          </p>
          <div className="mt-2 flex gap-2">
            <Button variant="danger" onClick={() => void decide(r.id, 'approved')}>
              {t.reversals.approve}
            </Button>
            <Button variant="secondary" onClick={() => void decide(r.id, 'rejected')}>
              {t.reversals.reject}
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function PendingAdvance() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const pending = useQuery({ queryKey: ['advance', 'pending'], queryFn: fetchPendingAdvance });
  const decide = async (id: number, decision: 'approved' | 'rejected') => {
    try {
      await decideAdvance(id, decision, null);
      toast.show({ message: t.advance.decided, tone: 'success' });
      await queryClient.invalidateQueries({ queryKey: ['advance'] });
    } catch (caught) {
      toast.show({ message: errorMessage(caught), tone: 'error' });
    }
  };
  if (pending.isPending) return <Loading />;
  if (pending.isError) return <ErrorState onRetry={() => void pending.refetch()} />;
  if (pending.data.length === 0) return <EmptyState message={t.advance.nonePending} />;
  return (
    <ul className="flex flex-col gap-3">
      {pending.data.map((tx) => (
        <li key={tx.id} className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
          <p className="font-medium">
            {t.advance.kinds[tx.kind] ?? tx.kind} · {formatRupees(-tx.amount_paise)}
          </p>
          <p>{tx.reason}</p>
          <p className="text-slate-600">
            {tx.allocations
              .map((a) => `${formatDate(a.rent_date)} ${formatRupees(a.amount_paise)}`)
              .join(', ')}
          </p>
          <div className="mt-2 flex gap-2">
            <Button onClick={() => void decide(tx.id, 'approved')}>{t.advance.approve}</Button>
            <Button variant="secondary" onClick={() => void decide(tx.id, 'rejected')}>
              {t.advance.reject}
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
