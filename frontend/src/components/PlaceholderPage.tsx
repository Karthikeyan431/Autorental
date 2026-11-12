import { strings } from '../lib/strings';

/** An empty page for a module that a later milestone builds. */
export function PlaceholderPage({ title, week }: { title: string; week: number }) {
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold text-slate-900">{title}</h1>
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6">
        <p className="text-sm font-medium text-teal-800">{strings.placeholder.comingIn(week)}</p>
        <p className="mt-1 text-sm text-slate-600">{strings.placeholder.body}</p>
      </div>
    </section>
  );
}
