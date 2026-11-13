import { describe, expect, it, vi } from 'vitest';

import { createRefreshCoordinator, type ChannelLike, type LockLike } from './refresh-coordinator';

/**
 * A fake of the server's refresh rules (backend/app/modules/auth/service.py): every use
 * rotates the token; a rotated token used again revokes the whole family.
 */
class FakeServer {
  private current = 'refresh-0';
  private readonly rotated = new Set<string>();
  revoked = false;
  calls = 0;

  /** The shared cookie jar of the browser: every tab sends the same cookie. */
  cookie = this.current;

  async refresh(sent: string): Promise<string> {
    this.calls += 1;
    await Promise.resolve(); // the request is in flight
    if (this.revoked) throw new Error('REFRESH_INVALID');
    if (this.rotated.has(sent)) {
      this.revoked = true; // reuse detected: the family is gone
      throw new Error('REFRESH_REUSED');
    }
    if (sent !== this.current) throw new Error('REFRESH_INVALID');
    this.rotated.add(sent);
    this.current = `refresh-${this.calls}`;
    this.cookie = this.current; // Set-Cookie reaches every tab
    return `access-${this.calls}`;
  }
}

/** One browser's Web Locks: callbacks for the same name run one after another. */
function fakeLocks(): LockLike {
  let tail: Promise<unknown> = Promise.resolve();
  return {
    request<T>(_name: string, callback: () => Promise<T>): Promise<T> {
      const run = tail.then(callback, callback);
      tail = run.catch(() => undefined);
      return run;
    },
  };
}

/** BroadcastChannel between tabs: a message reaches every other tab, not the sender. */
function fakeChannelHub() {
  const channels = new Set<ChannelLike>();
  return () => {
    const channel: ChannelLike = {
      onmessage: null,
      postMessage(message) {
        for (const other of channels) {
          if (other !== channel) other.onmessage?.({ data: message } as MessageEvent);
        }
      },
      close() {
        channels.delete(channel);
      },
    };
    channels.add(channel);
    return channel;
  };
}

function tab(server: FakeServer, locks: LockLike | undefined, channel: ChannelLike | null) {
  const received = vi.fn();
  const coordinator = createRefreshCoordinator<string>({
    // Each call reads the cookie at the moment the request is sent, like a browser.
    callRefresh: () => server.refresh(server.cookie),
    onRemoteRefresh: received,
    onRemoteSignOut: vi.fn(),
    locks,
    channel,
  });
  return { coordinator, received };
}

describe('refresh across tabs', () => {
  it('two tabs refreshing at once do not trigger reuse detection', async () => {
    const server = new FakeServer();
    const locks = fakeLocks();
    const channel = fakeChannelHub();
    const a = tab(server, locks, channel());
    const b = tab(server, locks, channel());

    const [first, second] = await Promise.all([a.coordinator.refresh(), b.coordinator.refresh()]);

    expect(server.revoked).toBe(false);
    expect(server.calls).toBe(1); // only one tab called /auth/refresh
    expect(first).toBe('access-1');
    expect(second).toBe('access-1'); // the other tab used the broadcast token
    expect(b.received).toHaveBeenCalledWith('access-1');

    // The session is still alive: a later refresh works.
    await expect(b.coordinator.refresh()).resolves.toBe('access-2');
    expect(server.revoked).toBe(false);
  });

  it('without the lock, the same race does trigger reuse detection (why the lock exists)', async () => {
    const server = new FakeServer();
    // Both tabs read the cookie before either response arrives.
    const sent = server.cookie;
    const results = await Promise.allSettled([server.refresh(sent), server.refresh(sent)]);
    expect(results.map((r) => r.status)).toEqual(['fulfilled', 'rejected']);
    expect(server.revoked).toBe(true);
  });

  it('a tab that has not received a newer result refreshes for itself', async () => {
    const server = new FakeServer();
    const locks = fakeLocks();
    const channel = fakeChannelHub();
    const a = tab(server, locks, channel());
    const b = tab(server, locks, channel());

    await expect(a.coordinator.refresh()).resolves.toBe('access-1');
    await expect(b.coordinator.refresh()).resolves.toBe('access-2');
    expect(server.calls).toBe(2);
    expect(server.revoked).toBe(false);
  });

  it('broadcasts sign-out to the other tabs', () => {
    const channel = fakeChannelHub();
    const signedOut = vi.fn();
    const a = createRefreshCoordinator<string>({
      callRefresh: async () => 'x',
      onRemoteRefresh: vi.fn(),
      onRemoteSignOut: vi.fn(),
      locks: fakeLocks(),
      channel: channel(),
    });
    createRefreshCoordinator<string>({
      callRefresh: async () => 'x',
      onRemoteRefresh: vi.fn(),
      onRemoteSignOut: signedOut,
      locks: fakeLocks(),
      channel: channel(),
    });
    a.announceSignOut();
    expect(signedOut).toHaveBeenCalledTimes(1);
  });

  it('still refreshes when Web Locks are not available', async () => {
    const server = new FakeServer();
    const { coordinator } = tab(server, undefined, null);
    await expect(coordinator.refresh()).resolves.toBe('access-1');
  });
});
