import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { Table, type Column } from '../../components/ui/Table';
import { useToast } from '../../components/ui/useToast';
import { containsAadhaarLike, NO_FULL_NUMBER_MESSAGE } from '../../lib/aadhaar';
import { ApiError } from '../../lib/api';
import { addDays, businessToday } from '../../lib/dates';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatDateTime, formatRupees } from '../../lib/format';
import { paiseToRupeesInput, parseSignedRupeesToPaise } from '../../lib/money';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import {
  decideAdjustment,
  fetchLedger,
  listAgreements,
  requestAdjustment,
  type AgreementStatus,
  type Eligibility,
  type LedgerRow,
} from './api';
import { dayLabel, dayTone, type DayTone } from './ledger';

const t = strings.agreements;
const l = strings.ledger;

const STATUS_TONES: Record<AgreementStatus, string> = {
  draft: 'bg-slate-50 text-slate-700 border-slate-200',
  active: 'bg-teal-50 text-teal-900 border-teal-200',
  ended: 'bg-sky-50 text-sky-900 border-sky-200',
  cancelled: 'bg-slate-50 text-slate-500 border-slate-200',
};

export function AgreementStatusBadge({ status }: { status: AgreementStatus }) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${STATUS_TONES[status]}`}
    >
      {t.statusLabels[status] ?? status}
    </span>
  );
}

const DAY_TONES: Record<DayTone, string> = {
  ok: 'bg-teal-50 text-teal-900 border-teal-200',
  warn: 'bg-amber-50 text-amber-900 border-amber-200',
  bad: 'bg-red-50 text-red-900 border-red-200',
  muted: 'bg-slate-50 text-slate-700 border-slate-200',
};

export function DayStatusBadge({ row }: { row: Pick<LedgerRow, 'status' | 'is_overdue'> }) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap ${DAY_TONES[dayTone(row)]}`}
    >
      {dayLabel(row)}
    </span>
  );
}

/** The live eligibility panel (requirements §4.9): every reason, in plain words. */
export function EligibilityPanel({
  eligibility,
  checking,
  ready,
}: {
  eligibility: Eligibility | undefined;
  checking: boolean;
  ready: boolean;
}) {
  let body;
  if (!ready) body = <p className="text-sm text-slate-600">{t.eligibilityPick}</p>;
  else if (checking || !eligibility)
    body = <p className="text-sm text-slate-600">{t.eligibilityChecking}</p>;
  else if (eligibility.ok) body = <p className="text-sm text-teal-900">{t.eligibilityOk}</p>;
  else
    body = (
      <ul className="list-disc pl-5 text-sm text-red-900" data-testid="eligibility-reasons">
        {eligibility.reasons.map((reason) => (
          <li key={reason.code}>{reason.message}</li>
        ))}
        {eligibility.vehicle_available_from && (
          <li>{t.availableFrom(formatDate(eligibility.vehicle_available_from))}</li>
        )}
      </ul>
    );
  return (
    <div
      aria-live="polite"
      className={`rounded-md border p-3 ${
        ready && eligibility && !eligibility.ok
          ? 'border-red-200 bg-red-50'
          : 'border-slate-200 bg-white'
      }`}
    >
      <h2 className="mb-1 text-sm font-semibold text-slate-900">{t.eligibility}</h2>
      {body}
    </div>
  );
}

/** Driver page: "Agreement and auto" tab. */
export function DriverAgreementsTab({ driverId }: { driverId: number }) {
  const { user } = useAuth();
  const agreements = useQuery({
    queryKey: ['agreements', { driverId }],
    queryFn: () => listAgreements({ page: 1, status: '', search: '', driverId }),
  });
  if (agreements.isPending) return <Loading />;
  if (agreements.isError) {
    return (
      <ErrorState
        requestId={agreements.error instanceof ApiError ? agreements.error.requestId : null}
        onRetry={() => void agreements.refetch()}
      />
    );
  }
  const items = agreements.data.items;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">{t.forDriver}</h2>
        {can(user, 'agreements.manage') && !items.some((a) => a.status === 'active') && (
          <Link
            to={`/agreements/new?driver=${driverId}`}
            className="rounded-md bg-teal-700 px-3 py-2 text-sm font-medium text-white"
          >
            {t.new}
          </Link>
        )}
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-slate-600">{t.noneForDriver}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((a) => (
            <li key={a.id} className="rounded-md border border-slate-200 p-3 text-sm">
              <p className="flex flex-wrap items-center justify-between gap-2">
                <Link to={`/agreements/${a.id}`} className="font-medium text-teal-800 underline">
                  {a.agreement_no}
                </Link>
                <AgreementStatusBadge status={a.status} />
              </p>
              <p className="text-slate-700">
                {a.vehicle.registration_number} · {formatRupees(a.daily_rent_paise)} ·{' '}
                {formatDate(a.start_date)}
                {a.end_date ? ` – ${formatDate(a.end_date)}` : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Driver page: "Rent ledger" tab. Day rows, totals and a date filter (Week 5). */
export function LedgerTab({ driverId }: { driverId: number }) {
  const { user } = useAuth();
  const today = businessToday();
  const [from, setFrom] = useState(addDays(today, -30));
  const [to, setTo] = useState(today);
  const [range, setRange] = useState({ from, to });
  const [adjusting, setAdjusting] = useState<LedgerRow | null>(null);
  const ledger = useQuery({
    queryKey: ['ledger', driverId, range],
    queryFn: () => fetchLedger(driverId, range.from, range.to),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });

  const columns: Column<LedgerRow>[] = [
    { key: 'date', header: l.date, render: (r) => formatDate(r.rent_date) },
    {
      key: 'charge',
      header: l.charge,
      align: 'right',
      render: (r) => formatRupees(r.charge_paise),
    },
    {
      key: 'adjustments',
      header: l.adjustments,
      align: 'right',
      render: (r) => (r.adjustments_paise ? formatRupees(r.adjustments_paise) : '—'),
    },
    {
      key: 'allocated',
      header: l.allocated,
      align: 'right',
      render: (r) => formatRupees(r.allocated_paise),
    },
    {
      key: 'balance',
      header: l.balance,
      align: 'right',
      render: (r) => formatRupees(r.balance_paise),
    },
    {
      key: 'status',
      header: l.status,
      render: (r) => (
        <div className="flex flex-col items-start gap-1">
          <DayStatusBadge row={r} />
          {r.awaiting_approval_paise > 0 && (
            <span className="text-xs text-amber-900">
              {l.awaiting(formatRupees(r.awaiting_approval_paise))}
            </span>
          )}
          {r.pending_adjustments_paise !== 0 && (
            <span className="text-xs text-slate-700">
              {l.pendingAdjustment(formatRupees(r.pending_adjustments_paise))}
            </span>
          )}
          {r.pending_adjustment_ids.length > 0 && can(user, 'adjustments.decide') && (
            <DecideButtons ids={r.pending_adjustment_ids} driverId={driverId} />
          )}
        </div>
      ),
    },
    { key: 'due', header: l.due, render: (r) => formatDateTime(r.due_at) },
  ];
  if (can(user, 'adjustments.request')) {
    columns.push({
      key: 'adjust',
      header: '',
      render: (r) => (
        <Button variant="secondary" onClick={() => setAdjusting(r)}>
          {l.requestAdjustment}
        </Button>
      ),
    });
  }

  if (ledger.isError && ledger.error instanceof ApiError && ledger.error.status === 404) {
    return <p className="text-sm text-slate-600">{l.notVisible}</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setRange({ from, to });
        }}
      >
        <Input label={l.from} type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Input label={l.to} type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        <Button type="submit" variant="secondary">
          {l.apply}
        </Button>
      </form>
      {ledger.isPending ? (
        <Loading />
      ) : ledger.isError ? (
        <ErrorState
          requestId={ledger.error instanceof ApiError ? ledger.error.requestId : null}
          onRetry={() => void ledger.refetch()}
        />
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="ledger-position">
            <Figure label={l.outstanding} value={formatRupees(ledger.data.outstanding_paise)} />
            <Figure label={l.overdue} value={formatRupees(ledger.data.overdue_paise)} />
          </dl>
          <Table
            caption={strings.drivers.tabs.ledger}
            columns={columns}
            rows={ledger.data.rows}
            getRowKey={(r) => r.charge_id}
            emptyMessage={l.none}
          />
          {ledger.data.rows.length > 0 && (
            <p className="text-sm text-slate-700" data-testid="ledger-totals">
              {l.totals}: {l.charge} {formatRupees(ledger.data.totals.charge_paise)} ·{' '}
              {l.adjustments} {formatRupees(ledger.data.totals.adjustments_paise)} · {l.allocated}{' '}
              {formatRupees(ledger.data.totals.allocated_paise)} · {l.balance}{' '}
              {formatRupees(ledger.data.totals.balance_paise)}
            </p>
          )}
        </>
      )}
      {adjusting && (
        <AdjustDialog row={adjusting} driverId={driverId} onClose={() => setAdjusting(null)} />
      )}
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 p-2">
      <dt className="text-xs text-slate-600">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums text-slate-900">{value}</dd>
    </div>
  );
}

function useLedgerRefresh(driverId: number) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['ledger', driverId] });
    await queryClient.invalidateQueries({ queryKey: ['rent-summary'] });
    await queryClient.invalidateQueries({ queryKey: ['adjustments'] });
  };
}

export function DecideButtons({ ids, driverId }: { ids: number[]; driverId: number | null }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const ledgerRefresh = useLedgerRefresh(driverId ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const decide = async (decision: 'approve' | 'reject') => {
    setBusy(true);
    setError(null);
    try {
      for (const id of ids) await decideAdjustment(id, decision, null);
      toast.show({ message: l.decided, tone: 'success' });
      if (driverId !== null) await ledgerRefresh();
      await queryClient.invalidateQueries({ queryKey: ['adjustments'] });
      await queryClient.invalidateQueries({ queryKey: ['rent-summary'] });
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-1">
      <div className="flex gap-1">
        <Button variant="secondary" loading={busy} onClick={() => void decide('approve')}>
          {l.approve}
        </Button>
        <Button variant="secondary" disabled={busy} onClick={() => void decide('reject')}>
          {l.reject}
        </Button>
      </div>
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

function AdjustDialog({
  row,
  driverId,
  onClose,
}: {
  row: LedgerRow;
  driverId: number;
  onClose: () => void;
}) {
  const toast = useToast();
  const refresh = useLedgerRefresh(driverId);
  const [amount, setAmount] = useState(`-${paiseToRupeesInput(row.charge_paise)}`);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const paise = parseSignedRupeesToPaise(amount);
    if (paise === null) {
      setError(l.adjustAmountInvalid);
      return;
    }
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
      await requestAdjustment(row.charge_id, paise, reason.trim());
      toast.show({ message: l.adjustRequested, tone: 'success' });
      await refresh();
      onClose();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open title={l.adjustTitle(formatDate(row.rent_date))} onClose={onClose}>
      <form noValidate className="flex flex-col gap-3" onSubmit={(event) => void submit(event)}>
        <p className="text-sm text-slate-700">{l.adjustHelp}</p>
        <Input
          label={l.adjustAmount}
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
        />
        <Input
          label={l.adjustReason}
          value={reason}
          maxLength={500}
          onChange={(e) => setReason(e.target.value)}
        />
        {error && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t.cancel}
          </Button>
          <Button type="submit" loading={busy}>
            {l.requestAdjustment}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
