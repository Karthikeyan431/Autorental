import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router';

import { ErrorState } from '../../components/ui/ErrorState';
import { Loading } from '../../components/ui/Loading';
import { ApiError } from '../../lib/api';
import { strings } from '../../lib/strings';
import { fetchDriver } from '../drivers/api';
import { fetchAttempt, fetchDriverKyc } from './api';
import {
  AttemptDetails,
  AttemptDocuments,
  AttemptHistory,
  DecisionPanel,
  StatusBadge,
} from './components';

const k = strings.kyc;

/** One attempt: the documents side by side with the details and the checklist. */
export default function KycReviewPage() {
  const { id } = useParams();
  const attemptId = Number(id);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const attempt = useQuery({
    queryKey: ['kyc-attempt', attemptId],
    queryFn: () => fetchAttempt(attemptId),
    enabled: Number.isInteger(attemptId) && attemptId > 0,
  });
  const driverId = attempt.data?.driver_id;
  const driver = useQuery({
    queryKey: ['driver', driverId],
    queryFn: () => fetchDriver(driverId ?? 0),
    enabled: driverId !== undefined,
  });

  if (attempt.isPending) {
    return (
      <section className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.kycReview}</h1>
        <Loading />
      </section>
    );
  }
  if (attempt.isError) {
    return (
      <section className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.kycReview}</h1>
        <ErrorState
          message={attempt.error instanceof ApiError ? attempt.error.message : undefined}
          requestId={attempt.error instanceof ApiError ? attempt.error.requestId : null}
        />
      </section>
    );
  }
  const data = attempt.data;
  const checkLabel = k.checkLabels[data.check_type] ?? data.check_type;

  const onChanged = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['kyc-attempt', attemptId] }),
      queryClient.invalidateQueries({ queryKey: ['driver-kyc', data.driver_id] }),
      queryClient.invalidateQueries({ queryKey: ['kyc-queue'] }),
      queryClient.invalidateQueries({ queryKey: ['kyc-counts'] }),
      queryClient.invalidateQueries({ queryKey: ['eligibility', data.driver_id] }),
    ]);
    // After a reopen, the current attempt is the new one.
    const refreshed = await fetchDriverKyc(data.driver_id);
    const current = refreshed[data.check_type];
    if (current && current.id !== data.id) void navigate(`/kyc/attempts/${current.id}`);
  };

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold text-slate-900">
          {k.reviewTitle(checkLabel, driver.data?.code ?? '…')}
        </h1>
        <div className="flex items-center gap-2 text-sm">
          {strings.drivers.attempt(data.attempt_no)} <StatusBadge status={data.status} />
          {data.is_simulated && (
            <span className="rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold">
              {k.simulated}
            </span>
          )}
        </div>
      </div>
      {driver.data && (
        <p className="text-sm text-slate-700">
          <Link to={`/drivers/${driver.data.id}`} className="text-teal-800 underline">
            {driver.data.full_name}
          </Link>{' '}
          · {strings.drivers.managedBy}: {driver.data.managed_by.name}
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <AttemptDocuments attempt={data} />
        </div>
        <div className="flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-4">
          <AttemptDetails attempt={data} />
          <DecisionPanel attempt={data} onChanged={onChanged} />
          <div>
            <h2 className="mb-1 text-sm font-semibold text-slate-900">{k.history}</h2>
            <AttemptHistory attempt={data} />
          </div>
        </div>
      </div>
    </section>
  );
}
