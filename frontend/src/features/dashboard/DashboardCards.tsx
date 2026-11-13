import { Link } from 'react-router';

import { strings } from '../../lib/strings';

/** A card with a figure (`value`), or a placeholder naming the week that fills it in. */
export type Card = { label: string; week: number; value?: number | null; to?: string };

export function DashboardCards({ cards }: { cards: Card[] }) {
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {cards.map((card) => {
        const live = card.value !== undefined;
        return (
          <li key={card.label} className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-sm text-slate-600">{card.label}</p>
            <p
              className={`mt-1 text-2xl font-semibold tabular-nums ${
                live ? 'text-slate-900' : 'text-slate-400'
              }`}
              data-testid={live ? `card-${card.label}` : undefined}
            >
              {live && card.value !== null ? card.value : strings.dashboard.pending}
            </p>
            {live ? (
              card.to && (
                <Link to={card.to} className="mt-1 inline-block text-xs text-teal-800 underline">
                  {strings.dashboard.openQueue}
                </Link>
              )
            ) : (
              <p className="mt-1 text-xs text-slate-500">{strings.dashboard.fromWeek(card.week)}</p>
            )}
          </li>
        );
      })}
    </ul>
  );
}
