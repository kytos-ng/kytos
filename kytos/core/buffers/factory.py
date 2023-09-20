"""Utilities for composing KytosEventBuffers"""
from functools import reduce

import limits
import limits.storage as lstorage
import limits.strategies as lstrategies
from janus import PriorityQueue, Queue

from .buffers import KytosEventBuffer, RateLimitedBuffer


def process_default(config: dict):
    """
    Create a default KytosEventBuffer from a given config dict
    """
    queue_classes = {
        'default': Queue,
        'queue': Queue,
        'priority': PriorityQueue,
    }
    return {
        'buffer_cls': KytosEventBuffer,
        'buffer_args': {
            'queue_cls': queue_classes[config.get('queue', 'default')]
        },
    }


def process_storage(config: dict):
    """
    Create a rate limit storage from a given config dict
    """
    storages = {
        'memory': lstorage.MemoryStorage,
    }
    return storages[config.get('type', 'memory')]()


def process_strategy(config: dict):
    """
    Create a rate limit strategy from a given config dict
    """
    strategies = {
        'moving_window': lstrategies.MovingWindowRateLimiter,
        'fixed_window': lstrategies.FixedWindowRateLimiter,
        'elastic_window': lstrategies.FixedWindowElasticExpiryRateLimiter,
    }
    strategy_cls = strategies[config.get('type', 'moving_window')]
    return strategy_cls(
        process_storage(
            config.get('storage', {})
        )
    )


def process_rate_limited(config: dict):
    """
    Create a rate limited KytosEventBuffer from a given config dict
    """
    processed = process_default(config)
    processed['buffer_cls'] = RateLimitedBuffer
    args = processed['buffer_args']
    args['strategy'] = process_strategy(config.get('strategy', {}))
    args['limit'] = limits.parse(config.get('limit', '100/second'))
    identifiers = [
        identifier.split('.')
        for identifier in config.get('identifier', [])
    ]
    args['gen_identifiers'] = lambda event: [
        reduce(
            lambda ev, attr: getattr(ev, attr, ('unknown',)),
            identifier,
            event
        )
        for identifier in identifiers
    ]
    return processed


def buffer_from_config(name: str, config: dict) -> KytosEventBuffer:
    """
    Create a KytosEventBuffer from a given config dict
    """
    buffer_conf_processors = {
        'default': process_default,
        'rate_limited': process_rate_limited,
    }
    buffer_type = config.get('type', 'default')
    processed_conf = buffer_conf_processors[buffer_type](config)
    return processed_conf['buffer_cls'](
        name,
        **(processed_conf['buffer_args'])
    )
