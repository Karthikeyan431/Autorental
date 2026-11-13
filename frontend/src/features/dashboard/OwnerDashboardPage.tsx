import { useQuery } from '@tanstack/react-query';

import { strings } from '../../lib/strings';
import { fetchVehicleSummary } from '../autos/api';
import { fetchQueueCounts } from '../kyc/api';
import { DashboardCards } from './DashboardCards';

const d = strings.dashboard;

/** Owner dashboard shell. Q28: both meanings of "active drivers" are shown, labelled. */
export default function OwnerDashboardPage() {
  // Rule 9: the same figures as the KYC queue tabs.
  const counts = useQuery({ queryKey: ['kyc-counts'], queryFn: fetchQueueCounts });
  const c = counts.data;
  const autos = useQuery({ queryKey: ['vehicle-summary'], queryFn: fetchVehicleSummary });
  const a = autos.data;
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.ownerDashboard}</h1>
      <p className="text-sm text-slate-600">{d.ownerIntro}</p>
      <DashboardCards
        cards={[
          { label: d.activeDriversWithAuto, week: 5 },
          { label: d.activeDriversApproved, week: 3 },
          {
            label: d.kycWaiting,
            week: 3,
            value: c ? c.pending + c.under_review + c.resubmission : null,
            to: '/kyc',
          },
          { label: d.licencesExpiring, week: 3, value: c ? c.expiring : null, to: '/kyc' },
          {
            label: d.papersExpiring,
            week: 4,
            value: a ? a.papers_expiring + a.papers_expired : null,
            to: '/autos',
            linkLabel: d.openAutos,
          },
          {
            label: d.autosAvailable,
            week: 4,
            value: a ? a.available : null,
            to: '/autos',
            linkLabel: d.openAutos,
          },
          { label: d.autosRented, week: 5 },
          { label: d.rentExpectedToday, week: 5 },
          { label: d.awaitingApproval, week: 6 },
          { label: d.openEscalations, week: 7 },
        ]}
      />
    </section>
  );
}
