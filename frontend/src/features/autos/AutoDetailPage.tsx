import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useParams } from 'react-router';

import { CaptureInput } from '../../components/CaptureInput';
import { SecureDocument } from '../../components/SecureDocument';
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
import { errorMessage } from '../../lib/errors';
import { formatDate, formatRupees } from '../../lib/format';
import { parseRupeesToPaise } from '../../lib/money';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import {
  addMaintenance,
  addPaper,
  changeVehicleStatus,
  fetchMaintenance,
  fetchPapers,
  fetchVehicle,
  type Paper,
  type PaperKind,
  type Vehicle,
  type VehicleStatus,
} from './api';
import { PaperStateBadge, VehicleFormDialog, VehicleStatusBadge } from './components';

const t = strings.autos;
type Tab = 'details' | 'papers' | 'maintenance';

/** One auto: details and status, papers with expiry, maintenance (requirements §4.8). */
export default function AutoDetailPage() {
  const id = Number(useParams().id);
  const [tab, setTab] = useState<Tab>('details');
  const query = useQuery({ queryKey: ['vehicle', id], queryFn: () => fetchVehicle(id) });

  if (query.isPending) return <Loading />;
  if (query.isError) {
    return (
      <ErrorState
        requestId={query.error instanceof ApiError ? query.error.requestId : null}
        onRetry={() => void query.refetch()}
      />
    );
  }
  const vehicle = query.data;
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">{vehicle.registration_number}</h1>
        <VehicleStatusBadge status={vehicle.status} />
      </div>
      <div role="tablist" aria-label={strings.pages.auto} className="flex gap-1 overflow-x-auto">
        {(['details', 'papers', 'maintenance'] as const).map((key) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`rounded-md px-3 py-2 text-sm whitespace-nowrap ${
              tab === key
                ? 'bg-teal-700 font-medium text-white'
                : 'bg-white text-slate-700 hover:bg-slate-100'
            }`}
          >
            {t.tabs[key]}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="rounded-lg border border-slate-200 bg-white p-4">
        {tab === 'details' && <DetailsTab vehicle={vehicle} />}
        {tab === 'papers' && <PapersTab vehicle={vehicle} />}
        {tab === 'maintenance' && <MaintenanceTab vehicle={vehicle} />}
      </div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex justify-between gap-3 border-b border-slate-100 py-1 text-sm">
      <dt className="text-slate-600">{label}</dt>
      <dd className="text-right text-slate-900">{value || '—'}</dd>
    </div>
  );
}

function useRefresh(id: number) {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ['vehicle', id] });
    await queryClient.invalidateQueries({ queryKey: ['vehicles'] });
    await queryClient.invalidateQueries({ queryKey: ['vehicle-summary'] });
  };
}

function DetailsTab({ vehicle }: { vehicle: Vehicle }) {
  const { user } = useAuth();
  const toast = useToast();
  const refresh = useRefresh(vehicle.id);
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState<VehicleStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const manage = can(user, 'vehicles.manage');

  const setStatus = async (status: VehicleStatus) => {
    setError(null);
    if (containsAadhaarLike(reason)) {
      setError(NO_FULL_NUMBER_MESSAGE);
      return;
    }
    setBusy(status);
    try {
      await changeVehicleStatus(vehicle.id, status, reason.trim() || null);
      setReason('');
      toast.show({ message: t.statusChanged, tone: 'success' });
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const targets = (['available', 'maintenance', 'inactive'] as const).filter(
    (s) => s !== vehicle.status,
  );
  return (
    <div className="flex flex-col gap-4">
      <dl>
        <Row label={t.registration} value={vehicle.registration_number} />
        <Row label={t.make} value={vehicle.make} />
        <Row label={t.model} value={vehicle.model} />
        <Row label={t.year} value={vehicle.year ? String(vehicle.year) : null} />
        <Row label={t.fuel} value={vehicle.fuel_type ? t.fuelTypes[vehicle.fuel_type] : null} />
        <Row label={t.notes} value={vehicle.notes} />
        <Row label={t.createdBy} value={vehicle.created_by?.name} />
      </dl>
      <p className="text-xs text-slate-600">{t.selectableNote}</p>
      {manage && (
        <div>
          <Button variant="secondary" onClick={() => setEditing(true)}>
            {strings.drivers.edit}
          </Button>
        </div>
      )}
      {manage && (
        <div className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold text-slate-900">{t.changeStatus}</h2>
          {vehicle.status === 'rented' ? (
            <p className="text-sm text-slate-600">{t.rentedNote}</p>
          ) : (
            <>
              <Input
                label={t.reason}
                value={reason}
                maxLength={500}
                onChange={(event) => setReason(event.target.value)}
              />
              {error && <Alert>{error}</Alert>}
              <div className="flex flex-col gap-2 sm:flex-row">
                {targets.map((status) => (
                  <Button
                    key={status}
                    variant="secondary"
                    loading={busy === status}
                    onClick={() => void setStatus(status)}
                  >
                    {t.setStatus(t.statusLabels[status] ?? status)}
                  </Button>
                ))}
              </div>
            </>
          )}
        </div>
      )}
      {editing && (
        <VehicleFormDialog
          vehicle={vehicle}
          onClose={() => setEditing(false)}
          onSaved={async () => {
            setEditing(false);
            await refresh();
          }}
        />
      )}
    </div>
  );
}

function PapersTab({ vehicle }: { vehicle: Vehicle }) {
  const { user } = useAuth();
  const history = useQuery({
    queryKey: ['vehicle-papers', vehicle.id],
    queryFn: () => fetchPapers(vehicle.id),
  });
  const [viewing, setViewing] = useState<Paper | null>(null);
  return (
    <div className="flex flex-col gap-4">
      {vehicle.papers.length === 0 ? (
        <p className="text-sm text-slate-600">{t.papersNone}</p>
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2" data-testid="current-papers">
          {vehicle.papers.map((paper) => (
            <li key={paper.id} className="rounded-md border border-slate-200 p-3 text-sm">
              <p className="flex items-center justify-between gap-2 font-medium text-slate-900">
                {t.paperKinds[paper.kind]} <PaperStateBadge state={paper.state} />
              </p>
              <p className="text-slate-700">
                {t.validUntil}: {formatDate(paper.valid_until)}
              </p>
              {paper.number && <p className="text-slate-600">{paper.number}</p>}
              {paper.document_id && paper.document_mime_type && (
                <button
                  type="button"
                  className="text-xs text-teal-800 underline"
                  onClick={() => setViewing(paper)}
                >
                  {t.viewPaper}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {can(user, 'vehicles.manage') && (
        <PaperForm vehicleId={vehicle.id} onSaved={() => void history.refetch()} />
      )}
      {history.data && history.data.length > 0 && (
        <div>
          <h2 className="mb-1 text-sm font-semibold text-slate-900">{t.history}</h2>
          <ul className="flex flex-col gap-1 text-sm text-slate-700">
            {history.data.map((paper) => (
              <li key={paper.id}>
                {t.paperKinds[paper.kind]} · {formatDate(paper.valid_until)}
                {paper.recorded_by ? ` · ${paper.recorded_by.name}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {viewing?.document_id && viewing.document_mime_type && (
        <Dialog open title={t.paperKinds[viewing.kind] ?? ''} onClose={() => setViewing(null)}>
          <SecureDocument
            documentId={viewing.document_id}
            mimeType={viewing.document_mime_type}
            label={t.paperKinds[viewing.kind] ?? ''}
            className="max-h-[70vh] w-full object-contain"
          />
        </Dialog>
      )}
    </div>
  );
}

function PaperForm({ vehicleId, onSaved }: { vehicleId: number; onSaved: () => void }) {
  const toast = useToast();
  const refresh = useRefresh(vehicleId);
  const [kind, setKind] = useState<PaperKind>('insurance');
  const [number, setNumber] = useState('');
  const [validFrom, setValidFrom] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [file, setFile] = useState<{ blob: Blob; name: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!validUntil) {
      setError(t.validUntilRequired);
      return;
    }
    if (containsAadhaarLike(number)) {
      setError(NO_FULL_NUMBER_MESSAGE);
      return;
    }
    setBusy(true);
    try {
      await addPaper(
        vehicleId,
        { kind, number: number.trim(), valid_from: validFrom, valid_until: validUntil },
        file,
      );
      toast.show({ message: t.paperSaved, tone: 'success' });
      setNumber('');
      setValidFrom('');
      setValidUntil('');
      setFile(null);
      onSaved();
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      noValidate
      onSubmit={(event) => void submit(event)}
      className="grid grid-cols-1 gap-3 rounded-md border border-slate-200 p-3 sm:grid-cols-2"
    >
      <h2 className="text-sm font-semibold text-slate-900 sm:col-span-2">{t.addPaper}</h2>
      <Select
        label={t.paperKind}
        value={kind}
        options={(['insurance', 'fitness', 'permit', 'pollution'] as const).map((value) => ({
          value,
          label: t.paperKinds[value] ?? value,
        }))}
        onChange={(event) => setKind(event.target.value as PaperKind)}
      />
      <Input
        label={t.paperNumber}
        value={number}
        maxLength={60}
        onChange={(event) => setNumber(event.target.value)}
      />
      <Input
        label={t.validFrom}
        type="date"
        value={validFrom}
        onChange={(event) => setValidFrom(event.target.value)}
      />
      <Input
        label={t.validUntil}
        type="date"
        value={validUntil}
        onChange={(event) => setValidUntil(event.target.value)}
      />
      <div className="sm:col-span-2">
        <CaptureInput
          label={t.paperFile}
          allowPdf
          done={file !== null}
          onFile={(blob, name) => setFile({ blob, name })}
        />
      </div>
      {error && (
        <div className="sm:col-span-2">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="flex justify-end sm:col-span-2">
        <Button type="submit" loading={busy}>
          {t.addPaper}
        </Button>
      </div>
    </form>
  );
}

function MaintenanceTab({ vehicle }: { vehicle: Vehicle }) {
  const { user } = useAuth();
  const toast = useToast();
  const records = useQuery({
    queryKey: ['vehicle-maintenance', vehicle.id],
    queryFn: () => fetchMaintenance(vehicle.id),
  });
  const [startedOn, setStartedOn] = useState('');
  const [endedOn, setEndedOn] = useState('');
  const [description, setDescription] = useState('');
  const [cost, setCost] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const costPaise = cost.trim() ? parseRupeesToPaise(cost) : null;
    if (cost.trim() && costPaise === null) {
      setError(t.costInvalid);
      return;
    }
    if (!startedOn || !description.trim()) {
      setError(t.required);
      return;
    }
    if (containsAadhaarLike(description)) {
      setError(NO_FULL_NUMBER_MESSAGE);
      return;
    }
    setBusy(true);
    try {
      await addMaintenance(vehicle.id, {
        started_on: startedOn,
        ended_on: endedOn || null,
        description: description.trim(),
        cost_paise: costPaise,
      });
      toast.show({ message: t.maintenanceSaved, tone: 'success' });
      setStartedOn('');
      setEndedOn('');
      setDescription('');
      setCost('');
      await records.refetch();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {records.data && records.data.length === 0 && (
        <p className="text-sm text-slate-600">{t.maintenanceNone}</p>
      )}
      {records.data && records.data.length > 0 && (
        <ul className="flex flex-col gap-2" data-testid="maintenance-list">
          {records.data.map((record) => (
            <li key={record.id} className="rounded-md border border-slate-200 p-3 text-sm">
              <p className="flex justify-between gap-2">
                <span className="font-medium text-slate-900">{record.description}</span>
                {record.cost_paise !== null && (
                  <span className="tabular-nums">{formatRupees(record.cost_paise)}</span>
                )}
              </p>
              <p className="text-slate-600">
                {formatDate(record.started_on)}
                {record.ended_on ? ` – ${formatDate(record.ended_on)}` : ''}
                {record.recorded_by ? ` · ${record.recorded_by.name}` : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
      {can(user, 'vehicles.manage') && (
        <form
          noValidate
          onSubmit={(event) => void submit(event)}
          className="grid grid-cols-1 gap-3 rounded-md border border-slate-200 p-3 sm:grid-cols-2"
        >
          <h2 className="text-sm font-semibold text-slate-900 sm:col-span-2">{t.addMaintenance}</h2>
          <Input
            label={t.startedOn}
            type="date"
            value={startedOn}
            onChange={(event) => setStartedOn(event.target.value)}
          />
          <Input
            label={t.endedOn}
            type="date"
            value={endedOn}
            onChange={(event) => setEndedOn(event.target.value)}
          />
          <Input
            label={t.description}
            value={description}
            maxLength={1000}
            onChange={(event) => setDescription(event.target.value)}
          />
          <Input
            label={t.cost}
            inputMode="decimal"
            value={cost}
            onChange={(event) => setCost(event.target.value)}
          />
          {error && (
            <div className="sm:col-span-2">
              <Alert>{error}</Alert>
            </div>
          )}
          <div className="flex justify-end sm:col-span-2">
            <Button type="submit" loading={busy}>
              {t.addMaintenance}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
