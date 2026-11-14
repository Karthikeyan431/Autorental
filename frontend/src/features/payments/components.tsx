import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Alert } from '../../components/ui/Alert';
import { Button } from '../../components/ui/Button';
import { Loading } from '../../components/ui/Loading';
import { errorMessage } from '../../lib/errors';
import { formatDate, formatRupees } from '../../lib/format';
import { paiseToRupeesInput, parseRupeesToPaise } from '../../lib/money';
import { strings } from '../../lib/strings';
import { type AllocationItem, type Payment } from './api';

const t = strings.payments;

const BADGE: Record<string, string> = {
  awaiting_approval: 'bg-amber-100 text-amber-900',
  approved: 'bg-emerald-100 text-emerald-900',
  rejected: 'bg-red-100 text-red-900',
  reversed: 'bg-slate-200 text-slate-800',
};

export function PaymentStatusBadge({ payment }: { payment: Pick<Payment, 'status'> }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${BADGE[payment.status] ?? ''}`}
    >
      {t.statusLabels[payment.status] ?? payment.status}
    </span>
  );
}

export type DayChoice = { rent_charge_id: number; rent_date: string; available_paise: number };

/**
 * Rule 4: the days a payment (or advance) covers. Pre-filled from a suggestion; staff can
 * change the amounts; nothing is saved until they press the button.
 */
export function DaysEditor({
  days,
  suggested,
  limitPaise,
  buttonLabel,
  onSubmit,
  help,
}: {
  days: DayChoice[];
  suggested: Record<number, number>;
  limitPaise: number;
  buttonLabel: string;
  onSubmit: (items: AllocationItem[]) => Promise<void>;
  help: string;
}) {
  // Pre-filled once from the suggestion; the parent remounts the editor (key) when it changes.
  const [values, setValues] = useState<Record<number, string>>(() =>
    Object.fromEntries(
      days.map((d) => {
        const amount = suggested[d.rent_charge_id] ?? 0;
        return [d.rent_charge_id, amount > 0 ? paiseToRupeesInput(amount) : ''];
      }),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parsed = days.map((d) => {
    const text = (values[d.rent_charge_id] ?? '').trim();
    return { day: d, text, paise: text === '' ? 0 : parseRupeesToPaise(text) };
  });
  const invalid = parsed.some((p) => p.paise === null);
  const total = parsed.reduce((sum, p) => sum + (p.paise ?? 0), 0);

  const submit = async () => {
    if (invalid) {
      setError(t.confirm.invalid);
      return;
    }
    if (total > limitPaise) {
      setError(t.confirm.overTotal);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(
        parsed
          .filter((p) => (p.paise ?? 0) > 0)
          .map((p) => ({ rent_charge_id: p.day.rent_charge_id, amount_paise: p.paise ?? 0 })),
      );
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  if (days.length === 0) return <Alert tone="info">{t.confirm.none}</Alert>;
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-slate-600">{help}</p>
      {error && <Alert>{error}</Alert>}
      <table className="min-w-full text-sm" aria-label={t.confirm.title}>
        <thead>
          <tr className="text-left text-slate-600">
            <th className="py-1">{t.confirm.day}</th>
            <th className="py-1 text-right">{t.confirm.left}</th>
            <th className="py-1 text-right">{t.confirm.pay}</th>
          </tr>
        </thead>
        <tbody>
          {days.map((d) => (
            <tr key={d.rent_charge_id}>
              <td className="py-1">{formatDate(d.rent_date)}</td>
              <td className="py-1 text-right tabular-nums">{formatRupees(d.available_paise)}</td>
              <td className="py-1 text-right">
                <input
                  aria-label={`${t.confirm.pay} ${formatDate(d.rent_date)}`}
                  inputMode="decimal"
                  className="w-24 rounded border border-slate-300 px-2 py-1 text-right"
                  value={values[d.rent_charge_id] ?? ''}
                  onChange={(event) =>
                    setValues((current) => ({
                      ...current,
                      [d.rent_charge_id]: event.target.value,
                    }))
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-sm tabular-nums" data-testid="days-total">
        {t.confirm.total(formatRupees(total), formatRupees(limitPaise))}
      </p>
      <div>
        <Button onClick={() => void submit()} loading={busy} disabled={invalid}>
          {buttonLabel}
        </Button>
      </div>
    </div>
  );
}

/** Loads the suggestion for a payment and shows the editor (confirm days or apply credit). */
export function ConfirmDays({
  payment,
  fetchSuggestionFor,
  save,
}: {
  payment: Payment;
  fetchSuggestionFor: (id: number) => Promise<{
    unallocated_paise: number;
    items: {
      rent_charge_id: number;
      rent_date: string;
      available_paise: number;
      amount_paise: number;
    }[];
  }>;
  save: (items: AllocationItem[]) => Promise<void>;
}) {
  const queryClient = useQueryClient();
  const credit = payment.status === 'approved';
  const suggestion = useQuery({
    queryKey: ['payment-suggestion', payment.id, payment.allocated_paise],
    queryFn: () => fetchSuggestionFor(payment.id),
  });
  if (suggestion.isPending) return <Loading />;
  if (suggestion.isError) return <Alert>{errorMessage(suggestion.error)}</Alert>;
  const days = suggestion.data.items.map((i) => ({
    rent_charge_id: i.rent_charge_id,
    rent_date: i.rent_date,
    available_paise: i.available_paise,
  }));
  const suggested = Object.fromEntries(
    suggestion.data.items.map((i) => [i.rent_charge_id, i.amount_paise]),
  );
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="mb-2 text-lg font-semibold">
        {credit ? t.confirm.creditTitle : t.confirm.title}
      </h2>
      <DaysEditor
        key={suggestion.dataUpdatedAt}
        days={days}
        suggested={suggested}
        limitPaise={suggestion.data.unallocated_paise}
        buttonLabel={credit ? t.confirm.apply : t.confirm.confirm}
        help={credit ? t.confirm.creditHelp : t.confirm.help}
        onSubmit={async (items) => {
          await save(items);
          await queryClient.invalidateQueries({ queryKey: ['payment-suggestion', payment.id] });
        }}
      />
    </div>
  );
}
