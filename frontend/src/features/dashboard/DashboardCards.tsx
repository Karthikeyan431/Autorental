import { strings } from '../../lib/strings';

export type Card = { label: string; week: number };

/** Placeholder figures: each card names the milestone that fills it in. */
export function DashboardCards({ cards }: { cards: Card[] }) {
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {cards.map((card) => (
        <li key={card.label} className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="text-sm text-slate-600">{card.label}</p>
          <p className="mt-1 text-2xl font-semibold text-slate-400 tabular-nums">
            {strings.dashboard.pending}
          </p>
          <p className="mt-1 text-xs text-slate-500">{strings.dashboard.fromWeek(card.week)}</p>
        </li>
      ))}
    </ul>
  );
}
