import { strings } from '../../lib/strings';
import { DashboardCards } from './DashboardCards';

const d = strings.dashboard;

/** Owner dashboard shell. Q28: both meanings of "active drivers" are shown, labelled. */
export default function OwnerDashboardPage() {
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.ownerDashboard}</h1>
      <p className="text-sm text-slate-600">{d.ownerIntro}</p>
      <DashboardCards
        cards={[
          { label: d.activeDriversWithAuto, week: 5 },
          { label: d.activeDriversApproved, week: 3 },
          { label: d.kycWaiting, week: 3 },
          { label: d.rentExpectedToday, week: 5 },
          { label: d.awaitingApproval, week: 6 },
          { label: d.openEscalations, week: 7 },
        ]}
      />
    </section>
  );
}
