"""Provides utilities for pacing actions."""
import asyncio
import logging
import time

import limits.aio.strategies
import limits.strategies
from limits import RateLimitItem, parse
from limits.storage import storage_from_string

from kytos.logging.filters import RepeateMessageFilter

LOG = logging.getLogger(__name__)

LOG.addFilter(RepeateMessageFilter(1.0, 512))


class EmptyStrategy(limits.strategies.FixedWindowRateLimiter):
    """Rate limiter, that doesn't actually rate limit."""

    def hit(
        self,
        item: RateLimitItem,
        *identifiers: str,
        cost: int = 1
    ) -> bool:
        # Increment storage, to collect data on usage rate of actions
        self.storage.incr(
            item.key_for(*identifiers),
            item.get_expiry(),
            elastic_expiry=False,
            amount=cost,
        )
        return True


class AsyncEmptyStrategy(limits.aio.strategies.FixedWindowRateLimiter):
    """Rate limiter, that doesn't actually rate limit."""

    async def hit(
        self,
        item: RateLimitItem,
        *identifiers: str,
        cost: int = 1
    ) -> bool:
        # Increment storage, to collect data on usage rate of actions
        await self.storage.incr(
            item.key_for(*identifiers),
            item.get_expiry(),
            elastic_expiry=False,
            amount=cost,
        )
        return True


available_strategies = {
    "fixed_window": (
        limits.strategies.FixedWindowRateLimiter,
        limits.aio.strategies.FixedWindowRateLimiter,
    ),
    "ignore_pace": (
        EmptyStrategy,
        AsyncEmptyStrategy,
    )
    # "elastic_window": (
    #     limits.strategies.FixedWindowElasticExpiryRateLimiter,
    #     limits.aio.strategies.FixedWindowElasticExpiryRateLimiter,
    # ),
}


class NoSuchActionError(BaseException):
    """
    Exception for trying to use actions that aren't configured.

    Not intended to be caught by NApps.
    """


class Pacer:
    """Class for controlling the rate at which actions are executed."""
    sync_strategies: dict[str, limits.strategies.RateLimiter]
    async_strategies: dict[str, limits.aio.strategies.RateLimiter]
    pace_config: dict[str, tuple[str, RateLimitItem]]

    def __init__(self, storage_uri):
        # Initialize dicts
        self.sync_strategies = {}
        self.async_strategies = {}
        self.pace_config = {}

        # Acquire storage
        sync_storage = storage_from_string(storage_uri)
        async_storage = storage_from_string(f"async+{storage_uri}")

        # Populate strategies
        for strat_name, strat_pair in available_strategies.items():
            sync_strat_type, async_strat_type = strat_pair
            self.sync_strategies[strat_name] = sync_strat_type(sync_storage)
            self.async_strategies[strat_name] = async_strat_type(async_storage)

    def inject_config(self, config: dict[str, dict]):
        """
        Inject settings for pacing
        """
        # Regenerate update dict
        next_config = {
            key: (
                value.get('strategy', 'fixed_window'),
                parse(value['pace'])
            )
            for key, value in config.items()
        }

        # Validate
        for action, (strat, _) in next_config.items():
            if strat not in available_strategies:
                raise ValueError(
                    f"Strategy ({strat}) for action ({action}) not valid"
                )
            LOG.info("Added pace for action %s", action)

        # Apply
        self.pace_config.update(
            next_config
        )

    async def ahit(self, action_name: str, *keys):
        """
        Asynchronous variant of `hit`.

        This can be called from the serving thread safely.
        """
        if action_name not in self.pace_config:
            raise NoSuchActionError(
                f"`{action_name}` has not been configured yet"
            )
        strat, pace = self.pace_config[action_name]
        identifiers = pace, action_name, *keys
        strategy = self.async_strategies[strat]
        while not await strategy.hit(*identifiers):
            window_reset, _ = await strategy.get_window_stats(
                *identifiers
            )
            sleep_time = window_reset - time.time()
            LOG.info(f'Limit reached: {identifiers}')
            await asyncio.sleep(sleep_time)

    def hit(self, action_name: str, *keys):
        """
        Pace execution, based on the pacing config for the given `action_name`.
        Keys can be included to allow multiple objects
        to be be paced separately on the same action.

        This should not be called from the same thread serving
        the pacing.
        """
        if action_name not in self.pace_config:
            raise NoSuchActionError(
                f"`{action_name}` has not been configured yet"
            )
        strat, pace = self.pace_config[action_name]
        identifiers = pace, action_name, *keys
        strategy = self.sync_strategies[strat]
        while not strategy.hit(*identifiers):
            window_reset, _ = strategy.get_window_stats(
                *identifiers
            )
            sleep_time = window_reset - time.time()
            LOG.info(f'Limited reached: {identifiers}')
            if sleep_time <= 0:
                continue

            time.sleep(sleep_time)

    def is_configured(self, action_name):
        """
        Check if the given action has been configured.
        """
        return action_name in self.pace_config


class PacerWrapper:
    """
    Applies a namespace to various operations related to pacing.
    """
    namespace: str
    pacer: Pacer

    def __init__(self, namespace: str, pacer: Pacer):
        self.namespace = namespace
        self.pacer = pacer

    def inject_config(self, napp_config: dict):
        """
        Inject namespace specific settings for pacing
        """
        self.pacer.inject_config(
            {
                self._localized_key(key): value
                for key, value in napp_config.items()
            }
        )

    def hit(self, action_name: str, *keys):
        """
        Asynchronous variant of `hit`.

        This can be called from the serving thread safely.
        """
        return self.pacer.hit(
            self._localized_key(action_name),
            *keys
        )

    async def ahit(self, action_name: str, *keys):
        """
        Pace execution, based on the pacing config for the given `action_name`.
        Keys can be included to allow multiple objects
        to be be paced separately on the same action.

        This should not be called from the same thread serving
        the pacing.
        """
        return await self.pacer.ahit(
            self._localized_key(action_name),
            *keys
        )

    def is_configured(self, action_name: str):
        """
        Check if the given action has been configured.
        """
        return self.pacer.is_configured(
            self._localized_key(action_name)
        )

    def _localized_key(self, key):
        return f"{self.namespace}.{key}"
