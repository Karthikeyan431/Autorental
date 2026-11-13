import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';

import { Button } from '../../components/ui/Button';
import { ErrorState } from '../../components/ui/ErrorState';
import { Input } from '../../components/ui/Input';
import { Loading } from '../../components/ui/Loading';
import { Table, type Column } from '../../components/ui/Table';
import { ApiError } from '../../lib/api';
import { formatDate, formatDateTime } from '../../lib/format';
import { strings } from '../../lib/strings';
import { fetchQueue, fetchQueueCounts, type Bucket, type QueueItem } from './api';
import { StatusBadge } from './components';

const k = strings.kyc;
const BUCKETS: Bucket[] = ['under_review', 'pending', 'resubmission', 'rejected', 'expiring'];

/** Rule 9: every driver's KYC shows here until done. Staff see the drivers they can decide on. */
export default function KycQueuePage() {
  const [bucket, setBucket] = useState<Bucket>('under_review');
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [searchText, setSearchText] = useState('');

  const counts = useQuery({ queryKey: ['kyc-counts'], queryFn: fetchQueueCounts });
  const queue = useQuery({
    queryKey: ['kyc-queue', bucket, page, search],
    queryFn: () => fetchQueue(bucket, page, search),
    placeholderData: keepPreviousData,
  });

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    setSearch(searchText);
    setPage(1);
  };

  const columns: Column<QueueItem>[] = [
    {
      key: 'driver',
      header: k.driver,
      render: (row) => (
        <Link to={`/drivers/${row.driver.id}`} className="text-teal-800 underline">
          {row.driver.code} · {row.driver.full_name}
        </Link>
      ),
    },
    { key: 'check', header: k.check, render: (row) => k.checkLabels[row.check_type] },
    { key: 'status', header: k.status, render: (row) => <StatusBadge status={row.status} /> },
    {
      key: 'when',
      header: bucket === 'expiring' ? k.validUntil : k.submitted,
      render: (row) =>
        bucket === 'expiring'
          ? row.licence_valid_until
            ? formatDate(row.licence_valid_until)
            : '—'
          : row.submitted_at
            ? formatDateTime(row.submitted_at)
            : '—',
    },
    {
      key: 'managed',
      header: strings.drivers.managedBy,
      render: (row) => row.driver.managed_by.name,
    },
    {
      key: 'open',
      header: k.open,
      render: (row) =>
        row.attempt_id && row.status !== 'draft' ? (
          <Link to={`/kyc/attempts/${row.attempt_id}`} className="text-teal-800 underline">
            {strings.drivers.review}
          </Link>
        ) : (
          <Link
            to={`/drivers/new?driver=${row.driver.id}&step=${row.check_type === 'identity' ? 3 : 4}`}
            className="text-teal-800 underline"
          >
            {strings.drivers.continueOnboarding}
          </Link>
        ),
    },
  ];

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.kycQueue}</h1>
      <div
        role="tablist"
        aria-label={strings.pages.kycQueue}
        className="flex gap-1 overflow-x-auto"
      >
        {BUCKETS.map((key) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={bucket === key}
            onClick={() => {
              setBucket(key);
              setPage(1);
            }}
            className={`rounded-md px-3 py-2 text-sm whitespace-nowrap ${
              bucket === key
                ? 'bg-teal-700 font-medium text-white'
                : 'bg-white text-slate-700 hover:bg-slate-100'
            }`}
          >
            {k.tabs[key]}
            {counts.data ? ` (${counts.data[key]})` : ''}
          </button>
        ))}
      </div>
      <form onSubmit={onSearch} className="flex max-w-md items-end gap-2">
        <div className="flex-1">
          <Input
            label={k.search}
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
          />
        </div>
        <Button type="submit" variant="secondary">
          {strings.drivers.searchButton}
        </Button>
      </form>
      {queue.isPending ? (
        <Loading />
      ) : queue.isError ? (
        <ErrorState
          requestId={queue.error instanceof ApiError ? queue.error.requestId : null}
          onRetry={() => void queue.refetch()}
        />
      ) : (
        <Table
          caption={k.tabs[bucket] ?? bucket}
          columns={columns}
          rows={queue.data.items}
          getRowKey={(row) => `${row.driver.id}-${row.check_type}`}
          emptyMessage={k.empty}
          pagination={{
            page: queue.data.page,
            pageSize: queue.data.page_size,
            total: queue.data.total,
            onPageChange: setPage,
          }}
        />
      )}
    </section>
  );
}
