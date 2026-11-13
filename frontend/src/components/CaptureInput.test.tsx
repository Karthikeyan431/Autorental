import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { CaptureInput } from './CaptureInput';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('CaptureInput', () => {
  it('uses the phone camera input first, and a file picker for PDFs', () => {
    render(<CaptureInput label="ID front" allowPdf onFile={() => undefined} />);
    expect(screen.getByTestId('capture-camera')).toHaveAttribute('capture', 'environment');
    expect(screen.getByTestId('capture-file')).toHaveAttribute(
      'accept',
      'image/jpeg,image/png,application/pdf',
    );
    expect(screen.getByRole('button', { name: 'Take photo: ID front' })).toBeVisible();
  });

  it('offers the live camera only in a secure context', () => {
    vi.stubGlobal('isSecureContext', true);
    vi.stubGlobal('navigator', {
      ...navigator,
      mediaDevices: { getUserMedia: () => Promise.reject(new Error('test')) },
    });
    render(<CaptureInput label="Driver photo" onFile={() => undefined} />);
    expect(screen.getByRole('button', { name: 'Use live camera: Driver photo' })).toBeVisible();
  });

  it('hands the chosen file over', async () => {
    const onFile = vi.fn();
    render(<CaptureInput label="ID front" onFile={onFile} />);
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'scan.jpg', { type: 'image/jpeg' });
    await userEvent.upload(screen.getByTestId('capture-file'), file);
    expect(onFile).toHaveBeenCalledWith(file, 'scan.jpg');
  });
});
