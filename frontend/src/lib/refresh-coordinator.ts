/**
 * One refresh at a time across every open tab.
 *
 * The refresh cookie is shared by all tabs and rotates on every use; the server treats a
 * rotated token used again as theft and revokes the whole session family. Two tabs refreshing
 * at the same moment would both send the same cookie, so the second one would sign everyone
 * out. To prevent that:
 *
 * - every refresh runs inside a Web Lock (`navigator.locks`), so tabs take turns;
 * - the tab that refreshes broadcasts the result on a BroadcastChannel;
 * - a tab that was waiting for the lock and has meanwhile received a newer result uses it
 *   instead of calling /auth/refresh with a cookie that has already been rotated.
 *
 * Sign-out is broadcast too, so every tab leaves together. Both APIs are same-origin only.
 * Without Web Locks (very old browsers, or a page opened over plain http, where browsers remove
 * navigator.locks) the refresh still works, but tabs are then not guaranteed to take turns.
 */

export const REFRESH_LOCK = 'arms-auth-refresh';
export const AUTH_CHANNEL = 'arms-auth';

export type LockLike = {
  request<T>(name: string, callback: () => Promise<T>): Promise<T>;
};

export type ChannelLike = {
  postMessage(message: unknown): void;
  close(): void;
  onmessage: ((event: MessageEvent) => void) | null;
};

type Message<T> = { type: 'refreshed'; result: T } | { type: 'signed-out' };

export type RefreshCoordinator<T> = {
  /** Resolves with a fresh result, from this tab's own call or from another tab's. */
  refresh: () => Promise<T>;
  announceSignOut: () => void;
  close: () => void;
};

export function createRefreshCoordinator<T>({
  callRefresh,
  onRemoteRefresh,
  onRemoteSignOut,
  locks = typeof navigator !== 'undefined' && navigator.locks ? navigator.locks : undefined,
  channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel(AUTH_CHANNEL) : null,
}: {
  callRefresh: () => Promise<T>;
  onRemoteRefresh: (result: T) => void;
  onRemoteSignOut: () => void;
  locks?: LockLike | undefined;
  channel?: ChannelLike | null;
}): RefreshCoordinator<T> {
  // Bumped by every result received from another tab.
  let generation = 0;
  let latest: T | null = null;
  let closed = false;

  const post = (message: Message<T>) => {
    if (!channel || closed) return;
    try {
      channel.postMessage(message);
    } catch {
      // A channel closed while a refresh was in flight; the other tabs simply refresh later.
    }
  };

  if (channel) {
    channel.onmessage = (event: MessageEvent) => {
      const message = event.data as Message<T>;
      if (message?.type === 'refreshed') {
        generation += 1;
        latest = message.result;
        onRemoteRefresh(message.result);
      } else if (message?.type === 'signed-out') {
        onRemoteSignOut();
      }
    };
  }

  async function refresh(): Promise<T> {
    const seen = generation;
    const run = async () => {
      // Another tab refreshed while this one waited: its cookie is already rotated.
      if (generation !== seen && latest !== null) return latest;
      const result = await callRefresh();
      post({ type: 'refreshed', result });
      return result;
    };
    return locks ? locks.request(REFRESH_LOCK, run) : run();
  }

  return {
    refresh,
    announceSignOut: () => post({ type: 'signed-out' }),
    close: () => {
      closed = true;
      if (channel) {
        channel.onmessage = null;
        channel.close();
      }
    },
  };
}
