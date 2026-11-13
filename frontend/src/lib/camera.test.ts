import { describe, expect, it } from 'vitest';

import { canUseLiveCamera } from './camera';

function fakeWindow(isSecureContext: boolean, withCamera: boolean): Window {
  const mediaDevices = withCamera ? { getUserMedia: () => Promise.resolve() } : undefined;
  return { isSecureContext, navigator: { mediaDevices } } as unknown as Window;
}

describe('canUseLiveCamera', () => {
  it('is offered on https or localhost when the browser has a camera API', () => {
    expect(canUseLiveCamera(fakeWindow(true, true))).toBe(true);
  });

  it('is hidden over plain http on the LAN', () => {
    expect(canUseLiveCamera(fakeWindow(false, true))).toBe(false);
  });

  it('is hidden when the browser has no camera API', () => {
    expect(canUseLiveCamera(fakeWindow(true, false))).toBe(false);
  });
});
