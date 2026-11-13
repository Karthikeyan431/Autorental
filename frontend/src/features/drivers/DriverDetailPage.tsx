import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router';

import { SecureImage } from '../../components/SecureDocument';
import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { Select } from '../../components/ui/Select';
import { useToast } from '../../components/ui/useToast';
import { containsAadhaarLike, NO_FULL_NUMBER_MESSAGE } from '../../lib/aadhaar';
import { ApiError } from '../../lib/api';
import { formatDate, formatDateTime } from '../../lib/format';
import { errorMessage } from '../../lib/errors';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import {
  AttemptDetails,
  AttemptDocuments,
  AttemptHistory,
  DecisionPanel,
  EligibilityPanel,
  StatusBadge,
} from '../kyc/components';
import { fetchDriverKyc, type Attempt } from '../kyc/api';
import {
  changeManager,
  fetchDriver,
  fetchManagerHistory,
  fetchManagers,
  fetchTimeline,
  type Driver,
} from './api';
import { DriverDetailsForm } from './DriverDetailsForm';

const t = strings.drivers;
type Tab = 'details' | 'kyc' | 'activity';

export default function DriverDetailPage() {
  const { id } = useParams();
  const driverId = Number(id);
  const query = useQuery({
    queryKey: ['driver', driverId],
    queryFn: () => fetchDriver(driverId),
    enabled: Number.isInteger(driverId) && driverId > 0,
  });
  const [tab, setTab] = useState<Tab>('details');

  if (query.isPending) {
    return (
      <section className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.driver}</h1>
        <Loading />
      </section>
    );
  }
  if (query.isError) {
    return (
      <section className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.driver}</h1>
        <ErrorState
          message={query.error instanceof ApiError ? query.error.message : undefined}
          requestId={query.error instanceof ApiError ? query.error.requestId : null}
        />
      </section>
    );
  }
  const driver = query.data;
  const tabs: { key: Tab; label: string }[] = [
    { key: 'details', label: t.tabs.details },
    { key: 'kyc', label: t.tabs.kyc },
    { key: 'activity', label: t.tabs.activity },
  ];

  return (
    <section className="flex flex-col gap-4">
      <DriverHeader driver={driver} />
      <div role="tablist" aria-label={strings.pages.driver} className="flex gap-1 overflow-x-auto">
        {tabs.map((item) => (
          <button
            key={item.key}
            role="tab"
            type="button"
            aria-selected={tab === item.key}
            onClick={() => setTab(item.key)}
            className={`rounded-md px-3 py-2 text-sm whitespace-nowrap ${
              tab === item.key
                ? 'bg-teal-700 font-medium text-white'
                : 'bg-white text-slate-700 hover:bg-slate-100'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'details' && <DetailsTab driver={driver} />}
        {tab === 'kyc' && <KycTab driver={driver} />}
        {tab === 'activity' && <ActivityTab driver={driver} />}
      </div>
    </section>
  );
}

function DriverHeader({ driver }: { driver: Driver }) {
  const { user } = useAuth();
  const [changing, setChanging] = useState(false);
  return (
    <header className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:flex-row">
      <div className="size-24 shrink-0 overflow-hidden rounded-md bg-slate-100">
        {driver.photo_document_id ? (
          <SecureImage
            documentId={driver.photo_document_id}
            label={strings.documents.labels.driver_photo ?? 'Driver photo'}
            className="size-24 object-cover"
          />
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-1">
        <h1 className="text-2xl font-semibold text-slate-900">{driver.full_name}</h1>
        <p className="text-sm text-slate-700">
          {driver.code} · {t.statusLabels[driver.account_status]} ·{' '}
          {driver.payment_rhythm === 'weekly' ? t.weekly : t.daily}
        </p>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          <div>
            <dt className="inline text-slate-600">{t.createdBy}: </dt>
            <dd className="inline font-medium text-slate-900" data-testid="created-by">
              {driver.created_by.name} {t.on(formatDate(driver.registered_at))}
            </dd>
          </div>
          <div>
            <dt className="inline text-slate-600">{t.managedBy}: </dt>
            <dd className="inline font-medium text-slate-900" data-testid="managed-by">
              {driver.managed_by.name}
              {driver.managed_since ? ` ${t.since(formatDate(driver.managed_since))}` : ''}
            </dd>
          </div>
        </dl>
      </div>
      {can(user, 'drivers.reassign') && (
        <div>
          <Button variant="secondary" onClick={() => setChanging(true)}>
            {t.changeManager}
          </Button>
        </div>
      )}
      {changing && <ChangeManagerDialog driver={driver} onClose={() => setChanging(false)} />}
    </header>
  );
}

function ChangeManagerDialog({ driver, onClose }: { driver: Driver; onClose: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const managers = useQuery({ queryKey: ['driver-managers'], queryFn: fetchManagers });
  const options = (managers.data ?? []).filter((m) => m.id !== driver.managed_by.id);
  const [staffId, setStaffId] = useState('');
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setError(null);
    const chosen = staffId || (options[0] ? String(options[0].id) : '');
    if (!chosen) return;
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
      const updated = await changeManager(driver.id, Number(chosen), reason.trim());
      queryClient.setQueryData(['driver', driver.id], updated);
      await queryClient.invalidateQueries({ queryKey: ['driver-activity', driver.id] });
      await queryClient.invalidateQueries({ queryKey: ['manager-history', driver.id] });
      toast.show({ message: t.managerChanged, tone: 'success' });
      onClose();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      title={t.changeManagerTitle}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t.cancel}
          </Button>
          <Button loading={busy} onClick={save} disabled={options.length === 0}>
            {t.save}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <Select
          label={t.newManager}
          value={staffId || (options[0] ? String(options[0].id) : '')}
          options={options.map((m) => ({ value: String(m.id), label: m.name }))}
          onChange={(event) => setStaffId(event.target.value)}
        />
        <Input
          label={t.reason}
          value={reason}
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
        />
        {error && <Alert>{error}</Alert>}
      </div>
    </Dialog>
  );
}

function DetailRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-100 py-2 text-sm">
      <dt className="text-slate-600">{label}</dt>
      <dd className="text-right text-slate-900">{value || '—'}</dd>
    </div>
  );
}

function DetailsTab({ driver }: { driver: Driver }) {
  const [editing, setEditing] = useState(false);
  const queryClient = useQueryClient();
  const toast = useToast();
  if (editing) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <DriverDetailsForm
          driver={driver}
          submitLabel={t.save}
          onCancel={() => setEditing(false)}
          onSaved={(updated) => {
            queryClient.setQueryData(['driver', driver.id], updated);
            toast.show({ message: t.saved, tone: 'success' });
            setEditing(false);
          }}
        />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4">
      <dl>
        <DetailRow label={t.mobile} value={driver.mobile} />
        <DetailRow label={t.altMobile} value={driver.alt_mobile} />
        <DetailRow label={t.address} value={driver.address} />
        <DetailRow label={t.dateOfBirth} value={formatDate(driver.date_of_birth)} />
        <DetailRow label={t.emergencyName} value={driver.emergency_name} />
        <DetailRow label={t.emergencyMobile} value={driver.emergency_mobile} />
        <DetailRow
          label={t.paymentRhythm}
          value={driver.payment_rhythm === 'weekly' ? t.weekly : t.daily}
        />
      </dl>
      {driver.can_edit ? (
        <div>
          <Button variant="secondary" onClick={() => setEditing(true)}>
            {t.edit}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-slate-600">{t.notEditable}</p>
      )}
    </div>
  );
}

function CheckCard({
  title,
  attempt,
  onChanged,
}: {
  title: string;
  attempt: Attempt | null;
  onChanged: () => Promise<unknown>;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
        <div className="flex items-center gap-2">
          <StatusBadge status={attempt?.status ?? null} />
          {attempt && (
            <Link to={`/kyc/attempts/${attempt.id}`} className="text-sm text-teal-800 underline">
              {t.review}
            </Link>
          )}
        </div>
      </div>
      {attempt ? (
        <>
          <AttemptDetails attempt={attempt} />
          <AttemptDocuments attempt={attempt} />
          <DecisionPanel attempt={attempt} onChanged={onChanged} />
        </>
      ) : null}
    </div>
  );
}

function KycTab({ driver }: { driver: Driver }) {
  const queryClient = useQueryClient();
  const kyc = useQuery({
    queryKey: ['driver-kyc', driver.id],
    queryFn: () => fetchDriverKyc(driver.id),
    enabled: driver.can_view_kyc,
  });
  if (!driver.can_view_kyc) return <Alert tone="info">{t.kycHidden}</Alert>;
  if (kyc.isPending) return <Loading />;
  if (kyc.isError) return <ErrorState onRetry={() => void kyc.refetch()} />;

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['driver-kyc', driver.id] }),
      queryClient.invalidateQueries({ queryKey: ['driver', driver.id] }),
      queryClient.invalidateQueries({ queryKey: ['eligibility', driver.id] }),
    ]);
  const data = kyc.data;
  const done = data.identity?.status === 'approved' && data.licence?.status === 'approved';
  const earlier = data.history.filter((a) => !a.is_current);

  return (
    <div className="flex flex-col gap-4">
      <EligibilityPanel driverId={driver.id} />
      {!done && driver.can_edit && (
        <div>
          <Link
            to={`/drivers/new?driver=${driver.id}`}
            className="inline-flex min-h-10 items-center rounded-md bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800"
          >
            {t.continueOnboarding}
          </Link>
        </div>
      )}
      <CheckCard title={t.identity} attempt={data.identity} onChanged={refresh} />
      <CheckCard title={t.licence} attempt={data.licence} onChanged={refresh} />
      {earlier.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-lg font-semibold text-slate-900">{strings.kyc.history}</h2>
          <ul className="flex flex-col gap-3">
            {earlier.map((attempt) => (
              <li key={attempt.id} className="flex flex-col gap-1">
                <p className="flex items-center gap-2 text-sm font-medium">
                  {strings.kyc.checkLabels[attempt.check_type]} · {t.attempt(attempt.attempt_no)}{' '}
                  <StatusBadge status={attempt.status} />
                </p>
                <AttemptHistory attempt={attempt} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ActivityTab({ driver }: { driver: Driver }) {
  const timeline = useQuery({
    queryKey: ['driver-activity', driver.id],
    queryFn: () => fetchTimeline(driver.id),
  });
  const history = useQuery({
    queryKey: ['manager-history', driver.id],
    queryFn: () => fetchManagerHistory(driver.id),
  });
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div className="rounded-lg border border-slate-200 bg-white p-4 lg:col-span-2">
        <h2 className="mb-2 text-lg font-semibold text-slate-900">{t.tabs.activity}</h2>
        {timeline.isPending ? (
          <Loading />
        ) : timeline.isError ? (
          <ErrorState onRetry={() => void timeline.refetch()} />
        ) : timeline.data.length === 0 ? (
          <p className="text-sm text-slate-600">{t.activityEmpty}</p>
        ) : (
          <ol className="flex flex-col divide-y divide-slate-100" data-testid="activity">
            {timeline.data.map((entry) => (
              <li key={entry.id} className="py-2 text-sm">
                <p className="font-medium text-slate-900">
                  {t.actions[entry.action] ?? entry.action}
                </p>
                <p className="text-slate-600">
                  {formatDateTime(entry.at)} · {entry.actor?.name ?? t.system}
                  {entry.reason ? ` · ${entry.reason}` : ''}
                </p>
              </li>
            ))}
          </ol>
        )}
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-lg font-semibold text-slate-900">{t.managerHistory}</h2>
        {history.data && (
          <ol className="flex flex-col gap-2 text-sm" data-testid="manager-history">
            {history.data.map((row) => (
              <li key={row.id}>
                <p className="font-medium text-slate-900">
                  {row.staff.name}
                  {row.to_at === null ? ` (${t.current})` : ''}
                </p>
                <p className="text-slate-600">
                  {formatDate(row.from_at)}
                  {row.to_at ? ` ${t.to} ${formatDate(row.to_at)}` : ''} ·{' '}
                  {t.changedBy(row.changed_by.name)}
                  {row.reason ? ` · ${row.reason}` : ''}
                </p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
