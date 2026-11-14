"""Bounded, priority-ordered concurrency limit.

At most `limit` requests run; up to `max_queue` wait, released lowest
priority value first (then FIFO). Beyond that, `QueueFullError` - backpressure,
not an unbounded pile-up in memory.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools


class QueueFullError(RuntimeError):
    pass


class PriorityLimiter:
    def __init__(self, limit: int, max_queue: int) -> None:
        self.limit = max(1, limit)
        self.max_queue = max(0, max_queue)
        self.active = 0
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._seq = itertools.count()

    @property
    def waiting(self) -> int:
        return sum(1 for _, _, f in self._waiters if not f.done())

    async def acquire(self, priority: int) -> None:
        if self.active < self.limit and not self.waiting:
            self.active += 1
            return
        if self.waiting >= self.max_queue:
            raise QueueFullError("gateway queue is full")
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._seq), future))
        try:
            await future
        except asyncio.CancelledError:
            if future.done() and not future.cancelled():
                self.release()  # slot was handed over; give it back
            raise

    def release(self) -> None:
        while self._waiters:
            _, _, future = heapq.heappop(self._waiters)
            if not future.done():
                future.set_result(None)  # slot passes directly to the waiter
                return
        self.active = max(0, self.active - 1)
