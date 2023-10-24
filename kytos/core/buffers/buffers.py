"""Kytos Buffer Classes, based on Python Queue."""
import asyncio
import logging
import time
from typing import Callable, Hashable, Iterable

import limits
import limits.aio.strategies as lstrategies
from janus import Queue

from kytos.core.events import KytosEvent

LOG = logging.getLogger(__name__)


class KytosEventBuffer:
    """KytosEventBuffer represents a queue to store a set of KytosEvents."""

    def __init__(self, name, event_base_class=None, maxsize=0,
                 queue_cls=Queue):
        """Contructor of KytosEventBuffer receive the parameters below.

        Args:
            name (string): name of KytosEventBuffer.
            event_base_class (class): Class of KytosEvent.
            maxsize (int): maxsize _queue producer buffer
            queue_cls (class): queue class from janus
        """
        self.name = name
        self._event_base_class = event_base_class
        self._queue = queue_cls(maxsize=maxsize)
        self._reject_new_events = False

    def put(self, event):
        """Insert an event in KytosEventBuffer if reject_new_events is False.

        Reject new events is True when a kytos/core.shutdown message was
        received.

        Args:
            event (:class:`~kytos.core.events.KytosEvent`):
                KytosEvent sent to queue.
        """
        if not self._reject_new_events:
            self._queue.sync_q.put(event)
            LOG.debug('[buffer: %s] Added: %s', self.name, event.name)

        if event.name == "kytos/core.shutdown":
            LOG.info('[buffer: %s] Stop mode enabled. Rejecting new events.',
                     self.name)
            self._reject_new_events = True

    async def aput(self, event):
        """Insert a event in KytosEventBuffer if reject new events is False.

        Reject new events is True when a kytos/core.shutdown message was
        received.

        Args:
            event (:class:`~kytos.core.events.KytosEvent`):
                KytosEvent sent to queue.
        """
        if not self._reject_new_events:
            await self._queue.async_q.put(event)
            LOG.debug('[buffer: %s] Added: %s', self.name, event.name)

        if event.name == "kytos/core.shutdown":
            LOG.info('[buffer: %s] Stop mode enabled. Rejecting new events.',
                     self.name)
            self._reject_new_events = True

    def get(self):
        """Remove and return a event from top of queue.

        Returns:
            :class:`~kytos.core.events.KytosEvent`:
                Event removed from top of queue.

        """
        event = self._queue.sync_q.get()
        LOG.debug('[buffer: %s] Removed: %s', self.name, event.name)

        return event

    async def aget(self):
        """Remove and return a event from top of queue.

        Returns:
            :class:`~kytos.core.events.KytosEvent`:
                Event removed from top of queue.

        """
        event = await self._queue.async_q.get()
        LOG.debug('[buffer: %s] Removed: %s', self.name, event.name)

        return event

    def task_done(self):
        """Indicate that a formerly enqueued task is complete.

        If a :func:`~kytos.core.buffers.KytosEventBuffer.join` is currently
        blocking, it will resume if all itens in KytosEventBuffer have been
        processed (meaning that a task_done() call was received for every item
        that had been put() into the KytosEventBuffer).
        """
        self._queue.sync_q.task_done()

    def join(self):
        """Block until all events are gotten and processed.

        A item is processed when the method task_done is called.
        """
        self._queue.sync_q.join()

    def qsize(self):
        """Return the size of KytosEventBuffer."""
        return self._queue.sync_q.qsize()

    def empty(self):
        """Return True if KytosEventBuffer is empty."""
        return self._queue.sync_q.empty()

    def full(self):
        """Return True if KytosEventBuffer is full of KytosEvent."""
        return self._queue.sync_q.full()


class RateLimitedBuffer(KytosEventBuffer):
    """
    Extension of KytosEventBuffer with ratelimiting capabilities.
    """
    def __init__(
        self, *args,
        strategy: lstrategies.RateLimiter,
        limit: limits.RateLimitItem,
        gen_identifiers: Callable[[KytosEvent], Iterable[Hashable]],
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.strategy = strategy
        self.limit = limit
        self.gen_identifiers = gen_identifiers

    async def aget(self):
        val = await super().aget()
        identifiers = self.limit, *self.gen_identifiers(val)
        while not await self.strategy.hit(*identifiers):
            window_reset, _ = await self.strategy.get_window_stats(*identifiers)
            sleep_time = window_reset - time.time()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        return val
