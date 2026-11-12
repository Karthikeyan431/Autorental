import type { Key, ReactNode } from 'react';

import { strings } from '../../lib/strings';
import { EmptyState } from './EmptyState';
import { Pagination, type PaginationProps } from './Pagination';

export type Column<T> = {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  /** Money and other numbers are right-aligned with tabular digits. */
  align?: 'left' | 'right';
};

export type TableProps<T> = {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  getRowKey: (row: T) => Key;
  emptyMessage?: string;
  pagination?: PaginationProps;
};

function alignClass(align: Column<unknown>['align']): string {
  return align === 'right' ? 'text-right tabular-nums' : 'text-left';
}

export function Table<T>({
  caption,
  columns,
  rows,
  getRowKey,
  emptyMessage = strings.common.nothingHereYet,
  pagination,
}: TableProps<T>) {
  return (
    <div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-slate-50">
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={`px-4 py-2 font-semibold whitespace-nowrap text-slate-700 ${alignClass(column.align)}`}
                >
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => (
              <tr key={getRowKey(row)} className="hover:bg-slate-50">
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={`px-4 py-2 text-slate-900 ${alignClass(column.align)}`}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <EmptyState message={emptyMessage} />}
      </div>
      {pagination && <Pagination {...pagination} />}
    </div>
  );
}
