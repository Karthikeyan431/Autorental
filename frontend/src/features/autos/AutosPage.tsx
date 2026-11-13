import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';

import { Button } from '../../components/ui/Button';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { Select } from '../../components/ui/Select';
import { Table, type Column } from '../../components/ui/Table';
import { ApiError } from '../../lib/api';
import { formatDate } from '../../lib/format';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import { listVehicles, type Vehicle, type VehicleFilters, type VehicleStatus } from './api';
import { PaperStateBadge, VehicleFormDialog, VehicleStatusBadge } from './components';

const t = strings.autos;

/** Autos list (requirements §4.8): status, papers needing attention, and "Add auto". */
export default function AutosPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<VehicleFilters>({ page: 1, search: '', status: '' });
  const [searchText, setSearchText] = useState('');
  const [adding, setAdding] = useState(false);

  const vehicles = useQuery({
    queryKey: ['vehicles', filters],
    queryFn: () => listVehicles(filters),
    placeholderData: keepPreviousData,
  });

  const update = (changes: Partial<VehicleFilters>) =>
    setFilters((current) => ({ ...current, ...changes, page: 1 }));

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    update({ search: searchText });
  };

  const columns: Column<Vehicle>[] = [
    {
      key: 'registration',
      header: t.registration,
      render: (v) => (
        <Link to={`/autos/${v.id}`} className="font-medium text-teal-800 underline">
          {v.registration_number}
        </Link>
      ),
    },
    { key: 'model', header: t.model, render: (v) => `${v.make} ${v.model}` },
    { key: 'status', header: t.status, render: (v) => <VehicleStatusBadge status={v.status} /> },
    {
      key: 'papers',
      header: t.papers,
      render: (v) => {
        const attention = v.papers.filter((p) => p.state !== 'ok');
        if (v.papers.length === 0) return t.noPapers;
        if (attention.length === 0) return <PaperStateBadge state="ok" />;
        return (
          <ul className="flex flex-col gap-1">
            {attention.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-1">
                <PaperStateBadge state={p.state} />
                <span className="text-xs text-slate-700">
                  {t.paperKinds[p.kind]} · {formatDate(p.valid_until)}
                </span>
              </li>
            ))}
          </ul>
        );
      },
    },
  ];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.autos}</h1>
        {can(user, 'vehicles.manage') && <Button onClick={() => setAdding(true)}>{t.add}</Button>}
      </div>

      <div className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-3 sm:grid-cols-2">
        <form onSubmit={onSearch} className="flex items-end gap-2">
          <div className="flex-1">
            <Input
              label={t.search}
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
            />
          </div>
          <Button type="submit" variant="secondary">
            {t.searchButton}
          </Button>
        </form>
        <Select
          label={t.status}
          value={filters.status}
          options={[
            { value: '', label: t.allStatuses },
            ...(['available', 'rented', 'maintenance', 'inactive'] as const).map((value) => ({
              value,
              label: t.statusLabels[value] ?? value,
            })),
          ]}
          onChange={(event) => update({ status: event.target.value as VehicleStatus | '' })}
        />
      </div>

      {vehicles.isPending ? (
        <Loading />
      ) : vehicles.isError ? (
        <ErrorState
          requestId={vehicles.error instanceof ApiError ? vehicles.error.requestId : null}
          onRetry={() => void vehicles.refetch()}
        />
      ) : (
        <Table
          caption={strings.pages.autos}
          columns={columns}
          rows={vehicles.data.items}
          getRowKey={(v) => v.id}
          emptyMessage={t.none}
          pagination={{
            page: vehicles.data.page,
            pageSize: vehicles.data.page_size,
            total: vehicles.data.total,
            onPageChange: (page) => setFilters((current) => ({ ...current, page })),
          }}
        />
      )}

      {adding && (
        <VehicleFormDialog
          vehicle={null}
          onClose={() => setAdding(false)}
          onSaved={async (saved) => {
            setAdding(false);
            await queryClient.invalidateQueries({ queryKey: ['vehicles'] });
            void navigate(`/autos/${saved.id}`);
          }}
        />
      )}
    </section>
  );
}
