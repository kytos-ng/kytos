"""Kytos Buffer Classes, based on Python Queue."""
import asyncio
import logging
import time
from typing import Callable, Hashable, Iterable

from janus import PriorityQueue, Queue
import limits

from kytos.core.events import KytosEvent
from kytos.core.helpers import get_thread_pool_max_workers

__all__ = ('KytosBuffers', )

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

    def __init__(self, *args,
                 strategy: limits.strategies.RateLimiter,
                 limit: limits.RateLimitItem,
                 gen_identifiers: Callable[[KytosEvent], Iterable[Hashable]], **kwargs):
        super().__init__(*args, **kwargs)
        self.strategy = strategy
        self.limit = limit
        self.gen_identifiers = gen_identifiers

    def get(self):
        val = super().get()
        identifiers = self.limit, *self.gen_identifiers(val)
        while not self.strategy.hit(*identifiers):
            window_reset, _ = self.strategy.get_window_stats(*identifiers)
            time.sleep(window_reset - time.time())
        return val

    async def aget(self):
        val = await super().aget()
        identifiers = self.limit, *self.gen_identifiers(val)
        while not self.strategy.hit(*identifiers):
            window_reset, _ = self.strategy.get_window_stats(*identifiers)
            await asyncio.sleep(window_reset - time.time())
        return val

class KytosBuffers:
    """Set of KytosEventBuffer used in Kytos."""

    def __init__(self):
        """Build four KytosEventBuffers.

        :attr:`conn`: :class:`~kytos.core.buffers.KytosEventBuffer` with events
        received from connection events.

        :attr:`raw`: :class:`~kytos.core.buffers.KytosEventBuffer` with events
        received from network.

        :attr:`msg_in`: :class:`~kytos.core.buffers.KytosEventBuffer` with
        events to be received.

        :attr:`msg_out`: :class:`~kytos.core.buffers.KytosEventBuffer` with
        events to be sent.

        :attr:`app`: :class:`~kytos.core.buffers.KytosEventBuffer` with events
        sent to NApps.
        """
        self._pool_max_workers = get_thread_pool_max_workers()
        self.conn = KytosEventBuffer("conn")
        self.raw = KytosEventBuffer("raw", maxsize=self._get_maxsize("sb"))
        self.msg_in = KytosEventBuffer("msg_in",
                                       maxsize=self._get_maxsize("sb"),
                                       queue_cls=PriorityQueue)
        self.msg_out = RateLimitedBuffer(
            "msg_out",
            maxsize=self._get_maxsize("sb"),
            queue_cls=PriorityQueue,
            strategy=limits.strategies.MovingWindowRateLimiter(limits.storage.MemoryStorage()),
            limit=limits.RateLimitItemPerSecond(100,1),
            gen_identifiers=lambda event: getattr(event.destination, 'id', ('unknown',)),
        )
        self.app = KytosEventBuffer("app", maxsize=self._get_maxsize("app"))

    def get_all_buffers(self):
        """Get all KytosEventBuffer instances."""
        return [
            event_buffer for event_buffer in self.__dict__.values()
            if isinstance(event_buffer, KytosEventBuffer)
        ]

    def _get_maxsize(self, queue_name):
        """Get queue maxsize if it's been set."""
        return self._pool_max_workers.get(queue_name, 0)

    def send_stop_signal(self):
        """Send a ``kytos/core.shutdown`` event to each buffer."""
        LOG.info('Stop signal received by Kytos buffers.')
        LOG.info('Sending KytosShutdownEvent to all apps.')
        event = KytosEvent(name='kytos/core.shutdown')
        for buffer in self.get_all_buffers():
            buffer.put(event)
