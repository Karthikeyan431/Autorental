import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link } from 'react-router';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Dialog } from '../../components/ui/Dialog';
import { EmptyState } from '../../components/ui/EmptyState';
import { ErrorState } from '../../components/ui/ErrorState';
import { Loading } from '../../components/ui/Loading';
import { useToast } from '../../components/ui/useToast';
import { ApiError } from '../../lib/api';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatDateTime, formatRupees } from '../../lib/format';
import { strings } from '../../lib/strings';
import { can, useAuth } from '../auth/auth-context';
import {
  fetchPayRequestQr,
  fetchPayRequests,
  generatePayRequests,
  markSent,
  type PayRequest,
} from '../payments/api';

const t = strings.payRequests;

/**
 * Pay requests today (requirements §4.10): one card per driver, built for a phone. "Send on
 * WhatsApp" is a link to wa.me (WhatsApp opens on the phone; staff press Send there) and the
 * tap is recorded. "Show QR" is for drivers paying at the office.
 */
export default function PayRequestsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [mine, setMine] = useState(user?.role === 'staff');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [qrFor, setQrFor] = useState<PayRequest | null>(null);
  const requests = useQuery({
    queryKey: ['pay-requests', mine],
    queryFn: () => fetchPayRequests(mine),
  });

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await generatePayRequests();
      toast.show({ message: t.generated(result.created, result.unchanged), tone: 'success' });
      await queryClient.invalidateQueries({ queryKey: ['pay-requests'] });
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.code === 'UPI_ID_NOT_SET'
          ? t.upiNotSet
          : errorMessage(caught),
      );
    } finally {
      setBusy(false);
    }
  };

  const sent = (request: PayRequest) => {
    // The link opens WhatsApp; recording the tap must not block it.
    void markSent(request.id)
      .then(() => queryClient.invalidateQueries({ queryKey: ['pay-requests'] }))
      .catch((caught: unknown) => toast.show({ message: errorMessage(caught), tone: 'error' }));
  };

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.payRequests}</h1>
        {can(user, 'payrequests.send') && (
          <Button onClick={() => void generate()} loading={busy}>
            {t.generate}
          </Button>
        )}
      </div>
      <p className="text-sm text-slate-600">{t.intro}</p>
      {error && <Alert>{error}</Alert>}
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={mine}
          onChange={(event) => setMine(event.target.checked)}
          className="size-4"
        />
        {t.mine}
      </label>
      {requests.isPending ? (
        <Loading />
      ) : requests.isError ? (
        <ErrorState
          requestId={requests.error instanceof ApiError ? requests.error.requestId : null}
          onRetry={() => void requests.refetch()}
        />
      ) : requests.data.length === 0 ? (
        <EmptyState message={t.none} />
      ) : (
        <ul className="flex flex-col gap-3" aria-label={strings.pages.payRequests}>
          {requests.data.map((request) => (
            <PayRequestCard
              key={request.id}
              request={request}
              canSend={can(user, 'payrequests.send')}
              onSent={() => sent(request)}
              onQr={() => setQrFor(request)}
            />
          ))}
        </ul>
      )}
      {qrFor && <QrDialog request={qrFor} onClose={() => setQrFor(null)} />}
    </section>
  );
}

function StateLine({ request }: { request: PayRequest }) {
  const parts: string[] = [];
  if (request.status === 'paid') parts.push(t.paid);
  else parts.push(t.open);
  parts.push(
    request.send_count > 0 && request.sent_at
      ? t.sent(request.send_count, formatDateTime(request.sent_at))
      : t.notSent,
  );
  if (request.awaiting_approval_paise > 0) {
    parts.push(t.awaiting(formatRupees(request.awaiting_approval_paise)));
  }
  const tone = request.status === 'paid' ? 'text-emerald-800' : 'text-slate-600';
  return <p className={`text-sm ${tone}`}>{parts.join(' · ')}</p>;
}

function PayRequestCard({
  request,
  canSend,
  onSent,
  onQr,
}: {
  request: PayRequest;
  canSend: boolean;
  onSent: () => void;
  onQr: () => void;
}) {
  const weekly = request.period_start !== request.period_end;
  return (
    <li
      className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white p-4"
      data-testid={`pay-request-${request.id}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <Link
            to={`/drivers/${request.driver.id}`}
            className="font-medium text-teal-800 underline"
          >
            {request.driver.full_name}
          </Link>
          <p className="text-xs text-slate-500">
            {request.driver.code} · {t.reference} {request.reference_code}
            {weekly &&
              ` · ${t.weekly(formatDate(request.period_start), formatDate(request.period_end))}`}
          </p>
        </div>
        <p className="text-xl font-semibold text-slate-900 tabular-nums">
          {formatRupees(request.amount_paise)}
        </p>
      </div>
      <StateLine request={request} />
      {request.mdr_warning && <Alert tone="warning">{t.mdrWarning}</Alert>}
      {request.status === 'open' && (
        <div className="flex flex-wrap gap-2">
          {canSend && (
            <a
              href={request.whatsapp_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onSent}
              className="inline-flex min-h-10 items-center rounded-md bg-emerald-700 px-4 text-sm font-medium text-white hover:bg-emerald-800"
            >
              {request.send_count > 0 ? t.sendAgain : t.send}
            </a>
          )}
          <Button variant="secondary" onClick={onQr}>
            {t.showQr}
          </Button>
        </div>
      )}
    </li>
  );
}

function QrDialog({ request, onClose }: { request: PayRequest; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchPayRequestQr(request.id)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [request.id]);
  return (
    <Dialog
      open
      title={t.qrTitle(request.reference_code)}
      onClose={onClose}
      footer={
        <Button variant="secondary" onClick={onClose}>
          {t.close}
        </Button>
      }
    >
      <div className="flex flex-col items-center gap-3">
        <p className="text-2xl font-semibold tabular-nums">{formatRupees(request.amount_paise)}</p>
        <p className="text-sm">{request.driver.full_name}</p>
        {failed ? (
          <Alert>{strings.common.somethingWentWrong}</Alert>
        ) : url ? (
          <img src={url} alt={t.qrTitle(request.reference_code)} className="w-full max-w-xs" />
        ) : (
          <Loading />
        )}
        <p className="text-xs text-slate-500">{t.qrHelp}</p>
      </div>
    </Dialog>
  );
}
