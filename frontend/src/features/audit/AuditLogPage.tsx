import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { ErrorState } from '../../components/ui/ErrorState';
import { Loading } from '../../components/ui/Loading';
import { Table, type Column } from '../../components/ui/Table';
import { apiFetch } from '../../lib/api';
import { formatDateTime } from '../../lib/format';
import { strings } from '../../lib/strings';
import type { PageOf } from '../staff/api';

const t = strings.audit;

type AuditEntry = {
  id: number;
  occurred_at: string;
  actor_id: number | null;
  actor_name: string | null;
  action: string;
  entity_type: string;
  entity_id: number | null;
  reason: string | null;
};

type ChainResult = { ok: boolean; checked: number; first_bad_id: number | null };

/** Minimal owner view (Week 2). Filters and export come in Week 8. */
export default function AuditLogPage() {
  const [page, setPage] = useState(1);
  const entries = useQuery({
    queryKey: ['audit-logs', page],
    queryFn: () => apiFetch<PageOf<AuditEntry>>(`/api/v1/audit-logs?page=${page}&page_size=25`),
  });
  const verify = useMutation({
    mutationFn: () => apiFetch<ChainResult>('/api/v1/audit-logs/verify'),
  });

  const columns: Column<AuditEntry>[] = [
    {
      key: 'when',
      header: t.when,
      render: (e) => <span className="whitespace-nowrap">{formatDateTime(e.occurred_at)}</span>,
    },
    { key: 'who', header: t.who, render: (e) => e.actor_name ?? t.system },
    {
      key: 'action',
      header: t.action,
      render: (e) => <span className="font-mono text-xs">{e.action}</span>,
    },
    {
      key: 'record',
      header: t.record,
      render: (e) => `${e.entity_type}${e.entity_id !== null ? ` #${e.entity_id}` : ''}`,
    },
    { key: 'reason', header: t.reason, render: (e) => e.reason ?? '' },
  ];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.auditLog}</h1>
          <p className="text-sm text-slate-600">{t.intro}</p>
          <p className="text-xs text-slate-500">{t.filtersLater}</p>
        </div>
        <Button variant="secondary" loading={verify.isPending} onClick={() => verify.mutate()}>
          {t.verify}
        </Button>
      </div>
      {verify.data && (
        <Alert tone={verify.data.ok ? 'success' : 'error'}>
          {verify.data.ok ? t.verifyOk(verify.data.checked) : t.verifyBad(verify.data.first_bad_id)}
        </Alert>
      )}
      {verify.isError && <Alert>{strings.common.somethingWentWrong}</Alert>}
      {entries.isPending && <Loading />}
      {entries.isError && <ErrorState onRetry={() => void entries.refetch()} />}
      {entries.data && (
        <Table
          caption={strings.pages.auditLog}
          columns={columns}
          rows={entries.data.items}
          getRowKey={(e) => e.id}
          pagination={{
            page: entries.data.page,
            pageSize: entries.data.page_size,
            total: entries.data.total,
            onPageChange: setPage,
          }}
        />
      )}
    </section>
  );
}
