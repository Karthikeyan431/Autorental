import { useAuth } from '../auth/auth-context';
import { strings } from '../../lib/strings';
import { DashboardCards } from './DashboardCards';

const d = strings.dashboard;

/** Staff dashboard shell: my drivers, my escalations, today's unpaid requests, my KYC work. */
export default function StaffDashboardPage() {
  const { user } = useAuth();
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.staffDashboard}</h1>
      <p className="text-sm text-slate-600">
        {user ? `${user.name}. ` : ''}
        {d.staffIntro}
      </p>
      <DashboardCards
        cards={[
          { label: d.myDrivers, week: 3 },
          { label: d.kycToFinish, week: 3 },
          { label: d.unpaidToday, week: 6 },
          { label: d.myEscalations, week: 7 },
        ]}
      />
    </section>
  );
}
