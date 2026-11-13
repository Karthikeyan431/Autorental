import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';

import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { Select } from '../../components/ui/Select';
import { Table, type Column } from '../../components/ui/Table';
import { Button } from '../../components/ui/Button';
import { ApiError } from '../../lib/api';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import { StatusBadge } from '../kyc/components';
import { fetchManagers, listDrivers, type DriverFilters, type DriverListItem } from './api';

const t = strings.drivers;

export default function DriversListPage() {
  const { user } = useAuth();
  const [filters, setFilters] = useState<DriverFilters>({
    page: 1,
    search: '',
    status: '',
    managedBy: user?.role === 'staff' ? 'me' : '',
    kyc: '',
  });
  const [searchText, setSearchText] = useState('');

  const drivers = useQuery({
    queryKey: ['drivers', filters],
    queryFn: () => listDrivers(filters),
    placeholderData: keepPreviousData,
  });
  const managers = useQuery({ queryKey: ['driver-managers'], queryFn: fetchManagers });

  const update = (changes: Partial<DriverFilters>) =>
    setFilters((current) => ({ ...current, ...changes, page: 1 }));

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    update({ search: searchText });
  };

  const columns: Column<DriverListItem>[] = [
    {
      key: 'driver',
      header: t.name,
      render: (d) => (
        <Link to={`/drivers/${d.id}`} className="font-medium text-teal-800 underline">
          {d.code} · {d.full_name}
        </Link>
      ),
    },
    { key: 'mobile', header: t.mobile, render: (d) => d.mobile },
    { key: 'managed', header: t.managedBy, render: (d) => d.managed_by.name },
    {
      key: 'identity',
      header: t.identity,
      render: (d) =>
        d.identity_status === null && d.licence_status === null ? (
          t.hidden
        ) : (
          <StatusBadge status={d.identity_status} />
        ),
    },
    {
      key: 'licence',
      header: t.licence,
      render: (d) =>
        d.identity_status === null && d.licence_status === null ? (
          t.hidden
        ) : (
          <StatusBadge status={d.licence_status} />
        ),
    },
    { key: 'status', header: t.status, render: (d) => t.statusLabels[d.account_status] },
  ];

  const managerOptions = [
    { value: '', label: t.anyone },
    { value: 'me', label: t.managedByMe },
    ...(managers.data ?? []).map((m) => ({ value: String(m.id), label: m.name })),
  ];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.drivers}</h1>
        {can(user, 'drivers.create') && (
          <Link
            to="/drivers/new"
            className="inline-flex min-h-10 items-center rounded-md bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800"
          >
            {t.register}
          </Link>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-3 sm:grid-cols-2 lg:grid-cols-4">
        <form onSubmit={onSearch} className="flex items-end gap-2 sm:col-span-2 lg:col-span-1">
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
          label={t.managedBy}
          value={filters.managedBy}
          options={managerOptions}
          onChange={(event) => update({ managedBy: event.target.value })}
        />
        <Select
          label={t.status}
          value={filters.status}
          options={[
            { value: '', label: t.allStatuses },
            { value: 'active', label: t.statusLabels.active ?? 'Active' },
            { value: 'suspended', label: t.statusLabels.suspended ?? 'Suspended' },
            { value: 'inactive', label: t.statusLabels.inactive ?? 'Inactive' },
          ]}
          onChange={(event) => update({ status: event.target.value as DriverFilters['status'] })}
        />
        <Select
          label={t.kyc}
          value={filters.kyc}
          options={[
            { value: '', label: t.kycAll },
            { value: 'verified', label: t.kycVerified },
            { value: 'not_verified', label: t.kycNotVerified },
          ]}
          onChange={(event) => update({ kyc: event.target.value as DriverFilters['kyc'] })}
        />
      </div>

      {drivers.isPending ? (
        <Loading />
      ) : drivers.isError ? (
        <ErrorState
          requestId={drivers.error instanceof ApiError ? drivers.error.requestId : null}
          onRetry={() => void drivers.refetch()}
        />
      ) : (
        <Table
          caption={strings.pages.drivers}
          columns={columns}
          rows={drivers.data.items}
          getRowKey={(d) => d.id}
          emptyMessage={t.none}
          pagination={{
            page: drivers.data.page,
            pageSize: drivers.data.page_size,
            total: drivers.data.total,
            onPageChange: (page) => setFilters((current) => ({ ...current, page })),
          }}
        />
      )}
    </section>
  );
}
