import { strings } from '../../lib/strings';

export function Loading({ label = strings.common.loading }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 px-4 py-6 text-sm text-slate-600">
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-teal-700 border-t-transparent"
      />
      {label}
    </div>
  );
}
