import { Link } from 'react-router';

import { strings } from '../lib/strings';

export function NotFoundPage() {
  return (
    <section className="flex flex-col gap-3">
      <h1 className="text-2xl font-semibold text-slate-900">{strings.pages.notFound}</h1>
      <p className="text-sm text-slate-600">{strings.notFound.body}</p>
      <Link to="/" className="text-sm font-medium text-teal-800 underline">
        {strings.notFound.home}
      </Link>
    </section>
  );
}
