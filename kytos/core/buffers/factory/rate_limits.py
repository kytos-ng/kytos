"""Factory for EventRateLimiter"""
from functools import partial
from typing import Callable

import limits
import limits.aio.storage as lstorage
import limits.aio.strategies as lstrategies

from kytos.core.buffers.rate_limit import (ConditionalRateLimiter,
                                           EventRateLimiter)

from .helpers import process_conditional, process_gen_identifiers

rate_limit_storages = {
    'memory': lstorage.MemoryStorage,
}


rate_limit_strategies = {
    'moving_window': lstrategies.MovingWindowRateLimiter,
    'fixed_window': lstrategies.FixedWindowRateLimiter,
    'elastic_window': lstrategies.FixedWindowElasticExpiryRateLimiter,
}


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


def process_default_rate_limit(limiter_cls, config: dict):
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

    return limiter_cls(**args)


def process_conditional_rate_limit(limiter_cls, config: dict):
    """
    Create a ConditionalRateLimiter from a given config dict
    """
    args = {}

    args['condition'] = process_conditional(
        config['condition']
    )

    return process_default_rate_limit(
        config,
        partial(limiter_cls, **args)
    )


limiter_processors: dict[Callable[[dict], EventRateLimiter]] = {
    'default': partial(
        process_default_rate_limit,
        EventRateLimiter
    ),
    'conditional': partial(
        process_conditional_rate_limit,
        ConditionalRateLimiter
    ),
}


def process_rate_limit(config: dict) -> EventRateLimiter:
    """
    Create a EventRateLimiter from a given config dict
    """

    processor = limiter_processors[config.get('type', 'default')]

    return processor(config)


def process_rate_limits(limit_configs: list[dict]):
    """
    Create a set of EventRateLimiters from a list of config dicts
    """
    return [
        process_rate_limit(config)
        for config in limit_configs
    ]
