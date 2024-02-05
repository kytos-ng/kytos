"""Kytos Buffer Classes, based on Python Queue."""
import asyncio
import logging
from typing import Optional

from janus import Queue

from kytos.core.buffers.rate_limit import EventRateLimiter
from kytos.core.events import KytosEvent

LOG = logging.getLogger(__name__)


class KytosEventBuffer:
    """KytosEventBuffer represents a queue to store a set of KytosEvents."""

    def __init__(
        self,
        name: str,
        queue: Queue = None,
        get_rate_limiters: list[EventRateLimiter] = None,
        put_rate_limiters: list[EventRateLimiter] = None,
    ):
        """Contructor of KytosEventBuffer receive the parameters below.

        Args:
            name (string): name of KytosEventBuffer.
            event_base_class (class): Class of KytosEvent.
            maxsize (int): maxsize _queue producer buffer
            queue_cls (class): queue class from janus
        """
        self.name = name
        self._queue = queue if queue is not None else Queue()
        self.get_rate_limiters = get_rate_limiters\
            if get_rate_limiters is not None else []
        self.put_rate_limiters = put_rate_limiters\
            if put_rate_limiters is not None else []
        self._reject_new_events = False

    def put(
        self,
        event: KytosEvent,
        timeout: Optional[float] = None
    ):
        """Insert an event in KytosEventBuffer if reject_new_events is False.

        Reject new events is True when a kytos/core.shutdown message was
        received.

        Args:
            event (:class:`~kytos.core.events.KytosEvent`):
                KytosEvent sent to queue.
            timeout: Block if necessary until a free slot is available.
            If 'timeout' is a non-negative number, it blocks at most 'timeout'
            seconds and raises an Full exception if no free slot was available.
        """
        # asyncio.run(self.check_put_rate_limits(event))
        if not self._reject_new_events:
            self._queue.sync_q.put(event, timeout=timeout)
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
        await self.check_put_rate_limits(event)
        if not self._reject_new_events:
            await self._queue.async_q.put(event)
            LOG.debug('[buffer: %s] Added: %s', self.name, event.name)

        if event.name == "kytos/core.shutdown":
            LOG.info('[buffer: %s] Stop mode enabled. Rejecting new events.',
                     self.name)
            self._reject_new_events = True

    def get(self) -> KytosEvent:
        """Remove and return a event from top of queue.

        Returns:
            :class:`~kytos.core.events.KytosEvent`:
                Event removed from top of queue.

        """
        event = self._queue.sync_q.get()
        # asyncio.run(self.check_get_rate_limits(event))
        LOG.debug('[buffer: %s] Removed: %s', self.name, event.name)

        return event

    async def aget(self) -> KytosEvent:
        """Remove and return a event from top of queue.

        Returns:
            :class:`~kytos.core.events.KytosEvent`:
                Event removed from top of queue.

        """
        event = await self._queue.async_q.get()
        await self.check_get_rate_limits(event)
        LOG.debug('[buffer: %s] Removed: %s', self.name, event.name)

        return event

    async def check_put_rate_limits(
        self,
        event: KytosEvent
    ):
        """
        Checks the event against the put rate limits.
        """
        await asyncio.gather(
            *map(
                lambda limiter: limiter(event),
                self.put_rate_limiters
            )
        )

    async def check_get_rate_limits(
        self,
        event: KytosEvent
    ):
        """
        Checks the event against the get rate limits.
        """
        await asyncio.gather(
            *map(
                lambda limiter: limiter(event),
                self.get_rate_limiters
            )
        )

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
