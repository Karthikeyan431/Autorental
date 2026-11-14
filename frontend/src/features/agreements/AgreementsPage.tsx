import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';

import { Button } from '../../components/ui/Button';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { Select } from '../../components/ui/Select';
import { Table, type Column } from '../../components/ui/Table';
import { ApiError } from '../../lib/api';
import { formatDate, formatRupees } from '../../lib/format';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import { listAgreements, type Agreement, type AgreementFilters, type AgreementStatus } from './api';
import { AgreementStatusBadge } from './components';

const t = strings.agreements;

/** Agreements list (requirements §4.9), with "New agreement". */
export default function AgreementsPage() {
  const { user } = useAuth();
  const [filters, setFilters] = useState<AgreementFilters>({ page: 1, status: '', search: '' });
  const [searchText, setSearchText] = useState('');
  const agreements = useQuery({
    queryKey: ['agreements', filters],
    queryFn: () => listAgreements(filters),
    placeholderData: keepPreviousData,
  });

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    setFilters((current) => ({ ...current, search: searchText, page: 1 }));
  };

  const columns: Column<Agreement>[] = [
    {
      key: 'number',
      header: t.number,
      render: (a) => (
        <Link to={`/agreements/${a.id}`} className="font-medium text-teal-800 underline">
          {a.agreement_no}
        </Link>
      ),
    },
    {
      key: 'driver',
      header: t.driver,
      render: (a) => (
        <Link to={`/drivers/${a.driver.id}`} className="text-teal-800 underline">
          {a.driver.full_name} ({a.driver.code})
        </Link>
      ),
    },
    { key: 'auto', header: t.auto, render: (a) => a.vehicle.registration_number },
    {
      key: 'rent',
      header: t.dailyRent,
      align: 'right',
      render: (a) => formatRupees(a.daily_rent_paise),
    },
    {
      key: 'dates',
      header: t.dates,
      render: (a) =>
        `${formatDate(a.start_date)}${a.end_date ? ` – ${formatDate(a.end_date)}` : ''}`,
    },
    { key: 'status', header: t.status, render: (a) => <AgreementStatusBadge status={a.status} /> },
  ];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.agreements}</h1>
        {can(user, 'agreements.manage') && (
          <Link
            to="/agreements/new"
            className="rounded-md bg-teal-700 px-4 py-2 text-sm font-medium text-white"
          >
            {t.new}
          </Link>
        )}
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
            ...(['draft', 'active', 'ended', 'cancelled'] as const).map((value) => ({
              value,
              label: t.statusLabels[value] ?? value,
            })),
          ]}
          onChange={(event) =>
            setFilters((current) => ({
              ...current,
              status: event.target.value as AgreementStatus | '',
              page: 1,
            }))
          }
        />
      </div>
      {agreements.isPending ? (
        <Loading />
      ) : agreements.isError ? (
        <ErrorState
          requestId={agreements.error instanceof ApiError ? agreements.error.requestId : null}
          onRetry={() => void agreements.refetch()}
        />
      ) : (
        <Table
          caption={strings.pages.agreements}
          columns={columns}
          rows={agreements.data.items}
          getRowKey={(a) => a.id}
          emptyMessage={t.none}
          pagination={{
            page: agreements.data.page,
            pageSize: agreements.data.page_size,
            total: agreements.data.total,
            onPageChange: (page) => setFilters((current) => ({ ...current, page })),
          }}
        />
      )}
    </section>
  );
}
