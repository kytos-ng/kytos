"""Mixins for event buffers."""

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Hashable, Iterable

import limits
import limits.aio.strategies as lstrategies

from kytos.core.events import KytosEvent


@dataclass
class EventRateLimiter:
    """
    Simple rate limit callable.
    """
    strategy: lstrategies.RateLimiter
    limit: limits.RateLimitItem
    gen_identifiers: Callable[[KytosEvent], Iterable[Hashable]]

    async def __call__(self, event: KytosEvent):
        """
        Pauses execution if rate limit for event exceeded.
        """
        identifiers = identifiers = self.limit, *self.gen_identifiers(event)
        while not await self.strategy.hit(*identifiers):
            window_reset, _ = await self.strategy.get_window_stats(
                *identifiers
            )
            sleep_time = window_reset - time.time()
            # Negative time is already checked by asyncio sleep
            await asyncio.sleep(sleep_time)


class ConditionalRateLimiter(EventRateLimiter):
    """
    Only rate limit if given condition is satisfied
    """
    condition: Callable[[KytosEvent], bool]

    async def __call__(self, event: KytosEvent):
        """Conditionally check event against rate limit"""
        if self.condition(event):
            return await super().__call__(event)
