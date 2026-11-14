import { useQuery } from '@tanstack/react-query';

import { useAuth } from '../auth/auth-context';
import { strings } from '../../lib/strings';
import { listDrivers } from '../drivers/api';
import { fetchQueueCounts } from '../kyc/api';
import { fetchPaymentsSummary } from '../payments/api';
import { DashboardCards } from './DashboardCards';

const d = strings.dashboard;

/** Staff dashboard shell: my drivers, my escalations, today's unpaid requests, my KYC work. */
export default function StaffDashboardPage() {
  const { user } = useAuth();
  const counts = useQuery({ queryKey: ['kyc-counts'], queryFn: fetchQueueCounts });
  const mine = useQuery({
    queryKey: ['drivers', 'mine-count'],
    queryFn: () => listDrivers({ page: 1, search: '', status: '', managedBy: 'me', kyc: '' }),
  });
  const c = counts.data;
  const payments = useQuery({ queryKey: ['payments-summary'], queryFn: fetchPaymentsSummary });
  const pay = payments.data;
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.staffDashboard}</h1>
      <p className="text-sm text-slate-600">
        {user ? `${user.name}. ` : ''}
        {d.staffIntro}
      </p>
      <DashboardCards
        cards={[
          {
            label: d.myDrivers,
            week: 3,
            value: mine.data ? mine.data.total : null,
            to: '/drivers',
          },
          {
            label: d.kycToFinish,
            week: 3,
            value: c ? c.pending + c.under_review + c.resubmission : null,
            to: '/kyc',
          },
          {
            label: d.unpaidToday,
            week: 6,
            value: pay ? pay.unpaid_today : null,
            to: '/pay-requests',
            linkLabel: d.openPayRequests,
          },
          { label: d.myEscalations, week: 7 },
        ]}
      />
    </section>
  );
}
