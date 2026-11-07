/** One request at a time; hidden/offline readers do not generate traffic. */
export type PollEnvironment = {
  active: () => boolean;
  later: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
  cancel: (id: ReturnType<typeof setTimeout>) => void;
  listen: (wake: () => void) => () => void;
};

export function browserPollEnvironment(): PollEnvironment {
  return {
    active: () => document.visibilityState === "visible" && navigator.onLine,
    later: (fn, ms) => setTimeout(fn, ms),
    cancel: id => clearTimeout(id),
    listen: wake => {
      document.addEventListener("visibilitychange", wake);
      window.addEventListener("online", wake);
      window.addEventListener("offline", wake);
      return () => {
        document.removeEventListener("visibilitychange", wake);
        window.removeEventListener("online", wake);
        window.removeEventListener("offline", wake);
      };
    },
  };
}

export function startPolling(
  read: (signal: AbortSignal) => Promise<void>,
  options: { intervalMs: number; timeoutMs?: number; maxBackoffMs?: number; onError?: (error: unknown) => void },
  env = browserPollEnvironment(),
): () => void {
  let stopped = false;
  let busy = false;
  let failures = 0;
  let wakeAfter = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  const clear = () => { if (timer !== undefined) env.cancel(timer); timer = undefined; };
  const schedule = (ms: number) => {
    clear();
    if (!stopped && env.active()) timer = env.later(() => { void pull(); }, ms);
  };
  const pull = async () => {
    clear();
    if (stopped || busy || !env.active()) return;
    busy = true;
    wakeAfter = false;
    const current = new AbortController();
    controller = current;
    let timedOut = false;
    const deadline = env.later(() => {
      timedOut = true;
      current.abort();
    }, options.timeoutMs ?? 10_000);
    try {
      await read(current.signal);
      if (timedOut) throw new Error("update timed out");
      if (!current.signal.aborted) failures = 0;
    } catch (error) {
      if (!stopped && (!current.signal.aborted || timedOut)) {
        failures++;
        options.onError?.(timedOut ? new Error("update timed out") : error);
      }
    } finally {
      env.cancel(deadline);
      busy = false;
      controller = undefined;
      const delay = Math.min(options.intervalMs * 2 ** Math.min(failures, 6), options.maxBackoffMs ?? 60_000);
      schedule(wakeAfter ? 0 : delay);
    }
  };
  const wake = () => {
    clear();
    if (!env.active()) { controller?.abort(); return; }
    if (busy) { wakeAfter = true; return; }
    void pull();
  };
  const unlisten = env.listen(wake);
  void pull();
  return () => { stopped = true; clear(); unlisten(); controller?.abort(); };
}

/** A malformed receipt must never reset the freshness clock. */
export function receiptTime(value: unknown): number {
  if (typeof value !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) throw new Error("invalid update timestamp");
  const time = Date.parse(value);
  if (!Number.isFinite(time)) throw new Error("invalid update timestamp");
  return time;
}
