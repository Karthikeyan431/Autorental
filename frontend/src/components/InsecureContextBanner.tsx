import { isInsecureContext } from '../lib/secure-context';
import { strings } from '../lib/strings';

/**
 * Shown on every screen when the page was opened over plain http. The app keeps working where
 * it can (request ids and the refresh lock have fallbacks); this explains what may not.
 */
export function InsecureContextBanner({ insecure = isInsecureContext() }: { insecure?: boolean }) {
  if (!insecure) return null;
  return (
    <div
      role="alert"
      className="border-b border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-950"
    >
      <p className="font-semibold">{strings.common.insecureTitle}</p>
      <p>{strings.common.insecureBody}</p>
    </div>
  );
}
