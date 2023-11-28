"""Mixins for event buffers."""

import asyncio
import time
from typing import Callable, Hashable, Iterable, TypedDict

import limits
import limits.aio.strategies as lstrategies

from kytos.core.events import KytosEvent


class RateLimitArgs(TypedDict):
    """
    Args dict for usage in rate limit mixins
    """
    strategy: lstrategies.RateLimiter
    limit: limits.RateLimitItem
    gen_identifiers: Callable[[KytosEvent], Iterable[Hashable]]


class GetRateLimitMixin:
    """
    Mixin for KytosEventBuffer to rate limit getting from the buffer.
    """
    def __init__(self, *args, get_rate_limit: RateLimitArgs, **kwargs):
        super().__init__(*args, **kwargs)
        self.__strategy = get_rate_limit['strategy']
        self.__limit = get_rate_limit['limit']
        self.__gen_identifiers = get_rate_limit['gen_identifiers']

    async def aget(self):
        """Rate limited async get"""
        val = await super().aget()
        identifiers = self.__limit, *self.__gen_identifiers(val)
        while not await self.__strategy.hit(*identifiers):
            window_reset, _ =\
                await self.__strategy.get_window_stats(*identifiers)
            sleep_time = window_reset - time.time()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        return val


class PutRateLimitMixin:
    """
    Mixin for KytosEventBuffer to rate limit putting into the buffer.
    """
    def __init__(self, *args, put_rate_limit: RateLimitArgs, **kwargs):
        super().__init__(*args, **kwargs)
        self.__strategy = put_rate_limit['strategy']
        self.__limit = put_rate_limit['limit']
        self.__gen_identifiers = put_rate_limit['gen_identifiers']

    async def aput(self, val):
        """Rate limited async put"""
        identifiers = self.__limit, *self.__gen_identifiers(val)
        while not await self.__strategy.hit(*identifiers):
            window_reset, _ =\
                await self.__strategy.get_window_stats(*identifiers)
            sleep_time = window_reset - time.time()
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        await super().aput(val)
