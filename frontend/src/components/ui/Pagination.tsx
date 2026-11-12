import { strings } from '../../lib/strings';
import { Button } from './Button';

export type PaginationProps = {
  page: number; // 1-based
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
};

export function Pagination({ page, pageSize, total, onPageChange }: PaginationProps) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav
      aria-label={strings.pagination.label}
      className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm text-slate-700"
    >
      <p>{total === 0 ? strings.pagination.none : strings.pagination.showing(from, to, total)}</p>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          aria-label={strings.pagination.previous}
        >
          ‹
        </Button>
        <Button
          variant="secondary"
          disabled={page >= lastPage}
          onClick={() => onPageChange(page + 1)}
          aria-label={strings.pagination.next}
        >
          ›
        </Button>
      </div>
    </nav>
  );
}
