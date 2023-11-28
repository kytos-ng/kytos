"""Utilities for composing KytosEventBuffers"""
from functools import reduce

import limits
import limits.aio.storage as lstorage
import limits.aio.strategies as lstrategies
from janus import PriorityQueue, Queue

from kytos.core.helpers import get_thread_pool_max_workers

from .buffers import KytosEventBuffer
from .mixin import GetRateLimitMixin, PutRateLimitMixin, RateLimitArgs

queue_classes = {
    'queue': Queue,
    'priority': PriorityQueue,
}

rate_limit_storages = {
    'memory': lstorage.MemoryStorage,
}

rate_limit_strategies = {
    'moving_window': lstrategies.MovingWindowRateLimiter,
    'fixed_window': lstrategies.FixedWindowRateLimiter,
    'elastic_window': lstrategies.FixedWindowElasticExpiryRateLimiter,
}


def process_queue(config: dict) -> Queue:
    """
    Create a janus queue from a given config dict
    """
    queue_type = queue_classes[config.get('type', 'queue')]
    queue_size = config.get('maxsize', 0)
    if isinstance(queue_size, str):
        if queue_size.startswith('threadpool_'):
            threadpool = queue_size[len('threadpool_'):]
            queue_size = get_thread_pool_max_workers().get(threadpool, 0)
        else:
            raise TypeError(
                'Expected int or str formatted '
                'as "threadpool_{threadpool_name}"'
            )
    return queue_type(maxsize=queue_size)


def process_storage(config: dict) -> lstorage.Storage:
    """
    Create a rate limit storage from a given config dict
    """
    return rate_limit_storages[config.get('type', 'memory')](
        uri=config.get('uri')
    )


def process_strategy(config: dict) -> lstrategies.RateLimiter:
    """
    Create a rate limiter from a given config dict
    """
    strategy_cls = rate_limit_strategies[config.get('type', 'moving_window')]
    return strategy_cls(
        process_storage(
            config.get('storage', {})
        )
    )


def process_gen_identifiers(identifiers: list[str]):
    """
    Generate a func for getting a tuple of hashable parameters from an event
    """
    split_identifiers = [
        identifier.split('.')
        for identifier in identifiers
    ]
    return lambda event: (
        reduce(
            lambda ev, attr: getattr(
                ev,
                attr,
                'unknown',
            ),
            identifier,
            event
        )
        for identifier in split_identifiers
    )


def process_rate_limit(config: dict) -> RateLimitArgs:
    """
    Create a rate limited KytosEventBuffer from a given config dict
    """
    args = {}
    args['strategy'] = process_strategy(
        config.get('strategy', {})
    )
    args['limit'] = limits.parse(
        config.get(
            'limit',
            '100/second'
        )
    )
    args['gen_identifiers'] = process_gen_identifiers(
        config.get('identifier', [])
    )
    return args


def process_get_rate_limit(config: dict):
    """
    Return class and parameters needed for get rate limit mixin
    """
    return GetRateLimitMixin, process_rate_limit(config)


def process_put_rate_limit(config: dict):
    """
    Return class and parameters needed for put rate limit mixin
    """
    return PutRateLimitMixin, process_rate_limit(config)


mixin_processors = {
    'get_rate_limit': process_get_rate_limit,
    'put_rate_limit': process_put_rate_limit,
}

__class_cache = {}


def combine_mixins(base_cls, mixins):
    """Combine mixins into the base_cls."""
    key = base_cls, frozenset(mixins)
    if key in __class_cache:
        return __class_cache[key]
    new_cls = type(
        base_cls.__name__,
        (*mixins, base_cls),
        {}
    )
    __class_cache[key] = new_cls
    return new_cls


def buffer_from_config(name: str, config: dict) -> KytosEventBuffer:
    """
    Create a KytosEventBuffer from a given config dict
    """
    buffer_cls = KytosEventBuffer
    args = {}
    # Process Queue Config
    args['queue'] = process_queue(config.get('queue', {}))

    # Process Mixins
    mixins: dict = config.get('mixins', {})
    mixin_classes = []
    for mixin, mixin_config in mixins.items():
        mixin_cls, mixin_args = mixin_processors[mixin](mixin_config)
        mixin_classes.append(mixin_cls)
        args[mixin] = mixin_args

    if mixin_classes:
        buffer_cls = combine_mixins(
            buffer_cls,
            mixin_classes
        )
    return buffer_cls(name, **args)
