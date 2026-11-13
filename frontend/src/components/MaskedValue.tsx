import { useState } from 'react';

import { revealField, type RevealField } from '../features/drivers/api';
import { errorMessage } from '../lib/errors';
import { strings } from '../lib/strings';

const t = strings.drivers;

/**
 * A masked identity value (D45). The owner and the driver's current manager can press "Show":
 * the value comes from POST /drivers/{id}/reveal (audited, rate-limited) and is held only in
 * this component's state, never in the query cache or browser storage, so it disappears when
 * the screen is left. Everyone else sees only the mask.
 */
export function MaskedValue({
  driverId,
  field,
  label,
  canReveal,
  attemptId,
  masked = t.masked,
  format,
}: {
  driverId: number;
  field: RevealField;
  label: string;
  canReveal: boolean;
  attemptId?: number;
  masked?: string;
  format?: (value: string) => string;
}) {
  const [value, setValue] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const show = async () => {
    setBusy(true);
    setError(null);
    try {
      const revealed = await revealField(driverId, field, attemptId);
      setValue(revealed.value);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-1 border-b border-slate-100 py-1 text-sm">
      <div className="flex items-center justify-between gap-3">
        <dt className="text-slate-600">{label}</dt>
        <dd className="flex items-center gap-2 text-right text-slate-900">
          <span data-testid={`masked-${field}`}>
            {value === null ? masked : format ? format(value) : value}
          </span>
          {canReveal &&
            (value === null ? (
              <button
                type="button"
                className="min-h-8 rounded px-2 text-xs font-medium text-teal-800 underline disabled:opacity-50"
                onClick={() => void show()}
                disabled={busy}
                aria-label={t.showField(label)}
              >
                {t.show}
              </button>
            ) : (
              <button
                type="button"
                className="min-h-8 rounded px-2 text-xs font-medium text-teal-800 underline"
                onClick={() => setValue(null)}
                aria-label={t.hideField(label)}
              >
                {t.hide}
              </button>
            ))}
        </dd>
      </div>
      {error && (
        <p role="alert" className="text-right text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
