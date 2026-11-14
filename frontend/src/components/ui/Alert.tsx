import type { ReactNode } from 'react';

type Tone = 'error' | 'info' | 'success' | 'warning';

const TONES: Record<Tone, string> = {
  error: 'border-red-200 bg-red-50 text-red-900',
  info: 'border-slate-200 bg-slate-50 text-slate-800',
  success: 'border-teal-200 bg-teal-50 text-teal-900',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
};

/** An inline message, e.g. a refused sign-in. Errors are announced to screen readers. */
export function Alert({ tone = 'error', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={`rounded-md border px-3 py-2 text-sm ${TONES[tone]}`}
    >
      {children}
    </div>
  );
}
