import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Button } from './Button';
import { Dialog } from './Dialog';
import { ErrorState } from './ErrorState';
import { Input } from './Input';
import { Loading } from './Loading';
import { Select } from './Select';
import { ToastProvider } from './Toast';
import { useToast } from './useToast';

describe('Button', () => {
  it('defaults to type=button and shows a busy state', () => {
    render(<Button loading>Save</Button>);
    const button = screen.getByRole('button', { name: /save/i });
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
  });
});

describe('Input and Select', () => {
  it('link the label, hint and error for screen readers', () => {
    render(<Input label="Mobile" hint="10 digits" error="Enter a valid mobile" />);
    const input = screen.getByLabelText('Mobile');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription(/Enter a valid mobile/);
    expect(input).toHaveAccessibleDescription(/10 digits/);
  });

  it('select renders its options with a label', () => {
    render(
      <Select
        label="Payment rhythm"
        options={[
          { value: 'daily', label: 'Daily' },
          { value: 'weekly', label: 'Weekly' },
        ]}
      />,
    );
    expect(screen.getByLabelText('Payment rhythm')).toHaveDisplayValue('Daily');
    expect(screen.getAllByRole('option')).toHaveLength(2);
  });
});

describe('Dialog', () => {
  it('is a labelled modal that closes on Escape', async () => {
    const onClose = vi.fn();
    render(
      <Dialog open title="Confirm payment" onClose={onClose}>
        Approve ₹300?
      </Dialog>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Confirm payment' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });

  it('renders nothing when closed', () => {
    render(
      <Dialog open={false} title="Hidden" onClose={() => {}}>
        x
      </Dialog>,
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('States', () => {
  it('loading announces itself', () => {
    render(<Loading />);
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i);
  });

  it('error state shows the request id and retries', async () => {
    const onRetry = vi.fn();
    render(
      <ErrorState message="Could not load drivers." requestId="abc123def456" onRetry={onRetry} />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Could not load drivers.');
    expect(screen.getByText(/abc123def456/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe('Toast', () => {
  function Trigger() {
    const toast = useToast();
    return <Button onClick={() => toast.show({ message: 'Saved', tone: 'success' })}>Go</Button>;
  }

  it('shows a polite status message', async () => {
    render(
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Go' }));
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(screen.getByText('Saved').closest('[aria-live]')).toHaveAttribute('aria-live', 'polite');
  });
});
