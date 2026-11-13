import { vi } from 'vitest';

type Reply =
  | { status?: number; body?: unknown }
  | ((init: RequestInit) => { status?: number; body?: unknown });

/**
 * Stub fetch with replies keyed by "METHOD /path" (query string ignored). Unknown routes get
 * 404; /api/v1/health is always ok. Returns the mock so tests can inspect calls.
 */
export function mockApi(routes: Record<string, Reply | Reply[]>) {
  const queues = new Map<string, Reply[]>(
    Object.entries(routes).map(([key, reply]) => [
      key,
      Array.isArray(reply) ? [...reply] : [reply],
    ]),
  );
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = typeof input === 'string' ? input : input.toString();
    const path = url.split('?')[0];
    const key = `${(init.method ?? 'GET').toUpperCase()} ${path}`;
    if (key === 'GET /api/v1/health' && !queues.has(key)) {
      return json(200, { status: 'ok', db: 'ok', version: 'test' });
    }
    const queue = queues.get(key);
    const next = queue && (queue.length > 1 ? queue.shift() : queue[0]);
    if (!next) {
      return json(404, { error: { code: 'NOT_FOUND', message: `No mock for ${key}` } });
    }
    const reply = typeof next === 'function' ? next(init) : next;
    if ((reply.status ?? 200) === 204) return new Response(null, { status: 204 });
    return json(reply.status ?? 200, reply.body ?? {});
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function apiError(status: number, code: string, message: string) {
  return { status, body: { error: { code, message, details: {}, request_id: 'testrequest01' } } };
}

/** The calls made to one route, with their parsed JSON bodies. */
export function callsTo(fetchMock: ReturnType<typeof mockApi>, method: string, path: string) {
  return fetchMock.mock.calls
    .filter(([input, init]) => {
      const url = typeof input === 'string' ? input : input.toString();
      return url.split('?')[0] === path && (init?.method ?? 'GET').toUpperCase() === method;
    })
    .map(([, init]) => ({
      headers: new Headers(init?.headers),
      body: typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : undefined,
    }));
}
