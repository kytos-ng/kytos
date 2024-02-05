"""Utilities for composing KytosEventBuffers"""
from functools import reduce

import limits
import limits.aio.storage as lstorage
import limits.aio.strategies as lstrategies
from janus import PriorityQueue, Queue

from kytos.core.helpers import get_thread_pool_max_workers

from .buffers import KytosEventBuffer
from .rate_limit import EventRateLimiter

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
    queue_size_multiplier = config.get('maxsize_multiplier', 1)
    if isinstance(queue_size, str):
        if queue_size.startswith('threadpool_'):
            threadpool = queue_size[len('threadpool_'):]
            queue_size = get_thread_pool_max_workers().get(threadpool, 0)
        else:
            raise TypeError(
                'Expected int or str formatted '
                'as "threadpool_{threadpool_name}"'
            )
    return queue_type(maxsize=queue_size * queue_size_multiplier)


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


def process_rate_limit(config: dict) -> EventRateLimiter:
    """
    Create a EventRateLimiter from a given config dict
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
    return EventRateLimiter(*args)


def process_rate_limits(limit_configs: list[dict]):
    """
    Create a set of EventRateLimiters from a list of config dicts
    """
    return [
        process_rate_limit(config)
        for config in limit_configs
    ]


extension_processors = {}


def buffer_from_config(name: str, config: dict) -> KytosEventBuffer:
    """
    Create a KytosEventBuffer from a given config dict
    """
    buffer_cls = KytosEventBuffer
    args = {}
    # Process Queue Config
    args['queue'] = process_queue(config.get('queue', {}))
    args['get_rate_limiters'] = process_rate_limits(
        config.get('get_rate_limiters', [])
    )
    args['put_rate_limiters'] = process_rate_limits(
        config.get('put_rate_limiters', [])
    )

    buffer = buffer_cls(name, **args)

    # Process Mixins
    extensions: dict = config.get('extensions', [])
    for extension in extensions:
        extension_type = extension['type']
        extension_args = extension.get('args', {})
        buffer = extension_processors[extension_type](buffer, extension_args)

    return buffer
