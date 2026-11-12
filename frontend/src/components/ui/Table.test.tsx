import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { formatRupees } from '../../lib/format';
import { Table, type Column } from './Table';

type Row = { id: number; name: string; rentPaise: number };

const columns: Column<Row>[] = [
  { key: 'name', header: 'Driver', render: (r) => r.name },
  { key: 'rent', header: 'Daily rent', align: 'right', render: (r) => formatRupees(r.rentPaise) },
];

const rows: Row[] = [
  { id: 1, name: 'Test Driver 001', rentPaise: 30000 },
  { id: 2, name: 'Test Driver 002', rentPaise: 12000050 },
];

describe('Table', () => {
  it('renders a header and one row per item', () => {
    render(<Table caption="Drivers" columns={columns} rows={rows} getRowKey={(r) => r.id} />);
    const table = screen.getByRole('table', { name: 'Drivers' });
    expect(within(table).getAllByRole('columnheader')).toHaveLength(2);
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(screen.getByText('₹1,20,000.50')).toBeInTheDocument();
  });

  it('right-aligns money columns, header and cells', () => {
    render(<Table caption="Drivers" columns={columns} rows={rows} getRowKey={(r) => r.id} />);
    expect(screen.getByRole('columnheader', { name: 'Daily rent' })).toHaveClass('text-right');
    expect(screen.getByText('₹300').closest('td')).toHaveClass('text-right', 'tabular-nums');
    expect(screen.getByText('Test Driver 001').closest('td')).not.toHaveClass('text-right');
  });

  it('shows the empty state when there are no rows', () => {
    render(
      <Table
        caption="Drivers"
        columns={columns}
        rows={[]}
        getRowKey={(r) => r.id}
        emptyMessage="No drivers yet"
      />,
    );
    expect(screen.getByText('No drivers yet')).toBeInTheDocument();
  });

  it('paginates: shows the range and moves between pages', async () => {
    const onPageChange = vi.fn();
    render(
      <Table
        caption="Drivers"
        columns={columns}
        rows={rows}
        getRowKey={(r) => r.id}
        pagination={{ page: 1, pageSize: 10, total: 25, onPageChange }}
      />,
    );
    expect(screen.getByText('Showing 1–10 of 25')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it('disables Next on the last page', () => {
    render(
      <Table
        caption="Drivers"
        columns={columns}
        rows={rows}
        getRowKey={(r) => r.id}
        pagination={{ page: 3, pageSize: 10, total: 25, onPageChange: () => {} }}
      />,
    );
    expect(screen.getByText('Showing 21–25 of 25')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
  });
});
