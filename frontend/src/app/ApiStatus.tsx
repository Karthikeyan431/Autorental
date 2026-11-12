import { useQuery } from '@tanstack/react-query';

import { apiFetch } from '../lib/api';
import { strings } from '../lib/strings';

type Health = { status: 'ok' | 'degraded'; db: 'ok' | 'unavailable'; version: string };

export function ApiStatus() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => apiFetch<Health>('/api/v1/health'),
    refetchInterval: 60_000,
    retry: false,
  });

  const online = health.data?.status === 'ok';
  const label = health.isPending
    ? strings.apiStatus.checking
    : online
      ? strings.apiStatus.online
      : strings.apiStatus.offline;

  return (
    <span className="inline-flex items-center gap-2 text-xs text-slate-600">
      <span
        aria-hidden="true"
        className={`size-2 rounded-full ${health.isPending ? 'bg-slate-400' : online ? 'bg-teal-600' : 'bg-red-600'}`}
      />
      {label}
    </span>
  );
}
