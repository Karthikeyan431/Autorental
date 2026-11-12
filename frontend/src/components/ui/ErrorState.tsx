import { strings } from '../../lib/strings';
import { Button } from './Button';

export function ErrorState({
  message = strings.common.somethingWentWrong,
  requestId,
  onRetry,
}: {
  message?: string;
  requestId?: string | null;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900"
    >
      <p className="font-medium">{message}</p>
      {requestId && <p className="text-xs text-red-800">{strings.common.requestId(requestId)}</p>}
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          {strings.common.tryAgain}
        </Button>
      )}
    </div>
  );
}
