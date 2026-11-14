import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { useToast } from '../../components/ui/useToast';
import { ApiError } from '../../lib/api';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatRupees } from '../../lib/format';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import { fetchLedger } from '../agreements/api';
import { fetchAdvance, requestAdvanceAdjustment } from './api';
import { DaysEditor } from './components';
import { PaymentsTable } from './PaymentsPage';

const t = strings.payments;
const a = t.advance;

/** The driver's payments and advance (requirements §4.4 "payments" tab; rule 5). */
export function DriverPaymentsTab({ driverId }: { driverId: number }) {
  const { user } = useAuth();
  return (
    <div className="flex flex-col gap-4">
      {can(user, 'payments.record') && (
        <div>
          <Link
            to={`/payments?tab=record&driver=${driverId}`}
            className="inline-block rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white"
          >
            {t.driverTab.record}
          </Link>
        </div>
      )}
      <PaymentsTable driverId={driverId} />
      <AdvanceSection driverId={driverId} />
    </div>
  );
}

function AdvanceSection({ driverId }: { driverId: number }) {
  const { user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [using, setUsing] = useState(false);
  const [reason, setReason] = useState('');
  const advance = useQuery({
    queryKey: ['advance', driverId],
    queryFn: () => fetchAdvance(driverId),
    retry: false,
  });
  const ledger = useQuery({
    queryKey: ['ledger-for-advance', driverId],
    queryFn: () => fetchLedger(driverId, '', ''),
    enabled: using,
  });
  if (advance.isPending) return <Loading />;
  // D54: only money viewers see the advance; others see nothing here.
  if (advance.isError) {
    // 404: this user may not see the driver's money (D54), so the section is left out.
    if (advance.error instanceof ApiError && advance.error.status === 404) return null;
    return <Alert>{errorMessage(advance.error)}</Alert>;
  }
  const v = advance.data;
  const available = v.balance_paise - v.pending_use_paise;
  const unpaid = (ledger.data?.rows ?? [])
    .filter((r) => r.balance_paise - r.awaiting_approval_paise > 0)
    .map((r) => ({
      rent_charge_id: r.charge_id,
      rent_date: r.rent_date,
      available_paise: r.balance_paise - r.awaiting_approval_paise,
    }));

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
      <h2 className="mb-2 text-lg font-semibold">{a.title}</h2>
      <p>
        {a.balance}:{' '}
        <span className="font-semibold tabular-nums" data-testid="advance-balance">
          {formatRupees(v.balance_paise)}
        </span>
        {v.pending_use_paise > 0 && ` · ${a.pendingUse}: ${formatRupees(v.pending_use_paise)}`}
      </p>
      {v.transactions.length === 0 ? (
        <p className="mt-2 text-slate-600">{a.none}</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-1">
          {v.transactions.map((tx) => (
            <li key={tx.id}>
              {formatDate(tx.created_at)} · {a.kinds[tx.kind] ?? tx.kind} ·{' '}
              <span className="tabular-nums">{formatRupees(tx.amount_paise)}</span> ·{' '}
              {a.statuses[tx.status] ?? tx.status}
            </li>
          ))}
        </ul>
      )}
      {can(user, 'adjustments.request') && available > 0 && (
        <div className="mt-3">
          {!v.adjustments_enabled ? (
            <Alert tone="info">{a.off}</Alert>
          ) : !using ? (
            <Button variant="secondary" onClick={() => setUsing(true)}>
              {a.use}
            </Button>
          ) : ledger.isPending ? (
            <Loading />
          ) : (
            <div className="flex flex-col gap-2">
              <Input
                label={a.reason}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
              <DaysEditor
                days={unpaid}
                suggested={{}}
                limitPaise={available}
                buttonLabel={a.use}
                help={a.useHelp}
                onSubmit={async (items) => {
                  await requestAdvanceAdjustment(driverId, items, reason.trim() || a.use);
                  toast.show({ message: a.requested, tone: 'success' });
                  setUsing(false);
                  await queryClient.invalidateQueries({ queryKey: ['advance', driverId] });
                }}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
