import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Table, type Column } from '../../components/ui/Table';
import { useToast } from '../../components/ui/useToast';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatRupees } from '../../lib/format';
import { strings } from '../../lib/strings';
import {
  fetchOverdue,
  fetchPendingAdjustments,
  fetchRentSummary,
  runAccrual,
  type Adjustment,
  type OverdueRow,
} from '../agreements/api';
import { DecideButtons } from '../agreements/components';
import { fetchVehicleSummary } from '../autos/api';
import { fetchQueueCounts } from '../kyc/api';
import { DashboardCards } from './DashboardCards';

const d = strings.dashboard;
const l = strings.ledger;

/** Owner dashboard. Q28: both meanings of "active drivers" are shown, labelled. */
export default function OwnerDashboardPage() {
  // Rule 9: the same figures as the KYC queue tabs.
  const counts = useQuery({ queryKey: ['kyc-counts'], queryFn: fetchQueueCounts });
  const c = counts.data;
  const autos = useQuery({ queryKey: ['vehicle-summary'], queryFn: fetchVehicleSummary });
  const a = autos.data;
  const rent = useQuery({ queryKey: ['rent-summary'], queryFn: fetchRentSummary });
  const r = rent.data;
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.ownerDashboard}</h1>
        <RunAccrualButton />
      </div>
      <p className="text-sm text-slate-600">{d.ownerIntro}</p>
      <DashboardCards
        cards={[
          {
            label: d.rentExpectedToday,
            week: 5,
            value: r ? formatRupees(r.rent_expected_today_paise) : null,
            to: '/agreements',
            linkLabel: d.openAgreements,
          },
          { label: d.overdueDrivers, week: 5, value: r ? r.overdue_drivers : null },
          { label: d.overdueAmount, week: 5, value: r ? formatRupees(r.overdue_paise) : null },
          {
            label: d.activeDriversWithAuto,
            week: 5,
            value: r ? r.active_agreements : null,
            to: '/agreements',
            linkLabel: d.openAgreements,
          },
          { label: d.activeDriversApproved, week: 3 },
          {
            label: d.kycWaiting,
            week: 3,
            value: c ? c.pending + c.under_review + c.resubmission : null,
            to: '/kyc',
          },
          { label: d.licencesExpiring, week: 3, value: c ? c.expiring : null, to: '/kyc' },
          {
            label: d.papersExpiring,
            week: 4,
            value: a ? a.papers_expiring + a.papers_expired : null,
            to: '/autos',
            linkLabel: d.openAutos,
          },
          {
            label: d.autosAvailable,
            week: 4,
            value: a ? a.available : null,
            to: '/autos',
            linkLabel: d.openAutos,
          },
          {
            label: d.autosRented,
            week: 5,
            value: a ? a.rented : null,
            to: '/autos',
            linkLabel: d.openAutos,
          },
          { label: d.adjustmentsPending, week: 5, value: r ? r.adjustments_pending : null },
          { label: d.awaitingApproval, week: 6 },
          { label: d.openEscalations, week: 7 },
        ]}
      />
      <PendingAdjustments />
      <OverdueList />
    </section>
  );
}

function RunAccrualButton() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await runAccrual();
      toast.show({ message: d.accrualDone(result.charges_created), tone: 'success' });
      for (const key of ['rent-summary', 'rent-overdue', 'ledger']) {
        await queryClient.invalidateQueries({ queryKey: [key] });
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="secondary" loading={busy} onClick={() => void run()}>
        {d.runAccrual}
      </Button>
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

function PendingAdjustments() {
  const pending = useQuery({ queryKey: ['adjustments'], queryFn: fetchPendingAdjustments });
  if (!pending.data || pending.data.length === 0) return null;
  const columns: Column<Adjustment>[] = [
    {
      key: 'day',
      header: l.date,
      render: (x) => (
        <Link to={`/drivers/${x.driver_id}`} className="text-teal-800 underline">
          {formatDate(x.rent_date)}
        </Link>
      ),
    },
    {
      key: 'amount',
      header: l.adjustments,
      align: 'right',
      render: (x) => formatRupees(x.amount_paise),
    },
    { key: 'reason', header: l.adjustReason, render: (x) => x.reason },
    { key: 'by', header: d.requestedBy, render: (x) => x.requested_by?.name ?? '—' },
    {
      key: 'decide',
      header: '',
      render: (x) => <DecideButtons ids={[x.id]} driverId={x.driver_id} />,
    },
  ];
  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold text-slate-900">{l.adjustmentsTitle}</h2>
      <Table
        caption={l.adjustmentsTitle}
        columns={columns}
        rows={pending.data}
        getRowKey={(x) => x.id}
      />
    </div>
  );
}

function OverdueList() {
  const overdue = useQuery({ queryKey: ['rent-overdue'], queryFn: fetchOverdue });
  const columns: Column<OverdueRow>[] = [
    {
      key: 'driver',
      header: d.driver,
      render: (o) => (
        <Link to={`/drivers/${o.driver_id}`} className="text-teal-800 underline">
          {o.driver_name} ({o.driver_code})
        </Link>
      ),
    },
    {
      key: 'amount',
      header: d.amount,
      align: 'right',
      render: (o) => formatRupees(o.overdue_paise),
    },
    {
      key: 'since',
      header: d.since,
      render: (o) => `${formatDate(o.oldest_overdue_date)} (${d.daysOverdue(o.days_overdue)})`,
    },
    { key: 'manager', header: d.managedBy, render: (o) => o.managed_by.name },
    {
      key: 'flag',
      header: '',
      render: (o) =>
        o.awaiting_approval_paise > 0 ? (
          <span className="text-xs text-amber-900">{d.awaitingFlag}</span>
        ) : null,
    },
  ];
  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold text-slate-900">{d.overdueTitle}</h2>
      <Table
        caption={d.overdueTitle}
        columns={columns}
        rows={overdue.data ?? []}
        getRowKey={(o) => o.driver_id}
        emptyMessage={d.overdueNone}
      />
    </div>
  );
}
