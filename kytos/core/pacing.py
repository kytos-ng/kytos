"""Provides utilities for pacing actions."""
import asyncio
import threading
from dataclasses import dataclass, field
import logging

from janus import Queue


LOG = logging.getLogger(__name__)


@dataclass
class Pacer:
    """Class for controlling the rate at which actions are executed."""
    pace_config: dict[str, tuple[int, float]] = field(default_factory=dict)
    pending: Queue = field(default=None)
    scheduling: dict[tuple, tuple[asyncio.Semaphore, asyncio.Queue]] = field(default_factory=dict)

    async def serve(self):
        LOG.info("Starting pacer.")
        if self.pending is not None:
            LOG.error("Tried to start pacer, already started.")
        
        self.pending = Queue()

        queue = self.pending.async_q

        try:
            async with asyncio.TaskGroup() as tg:
                while True:
                    event, action_name, keys = await queue.get()

                    if action_name not in self.pace_config:
                        LOG.warning("Pace for `%s` is not set", action_name)
                        event.set()
                        continue

                    max_concurrent, _ = self.pace_config[action_name]

                    keys = action_name, *keys

                    if keys not in self.scheduling:
                        max_concurrent, _ = self.pace_config[action_name]
                        self.scheduling[keys] = (
                            asyncio.Semaphore(max_concurrent),
                            asyncio.Queue()
                        )

                    _, sub_queue = self.scheduling[keys]

                    await sub_queue.put(event)
                    tg.create_task(self.__process_one(*keys))
        except Exception as ex:
            LOG.error("Pacing encounter error %s", ex)
            raise ex
        finally:
            LOG.info("Shutting down pacer.")
            self.pending = None

    async def __process_one(
        self,
        action_name: str,
        *keys
    ):
        """Ensure's fairness in dispatch."""

        keys = action_name, *keys

        semaphore, queue = self.scheduling[keys]
        _, refresh_period = self.pace_config[action_name]

        if semaphore.locked():
            LOG.warn("Pace limit reached on %s", keys)

        async with semaphore:
            event: asyncio.Event = queue.get_nowait()
            event.set()
            await asyncio.sleep(refresh_period)

    async def ahit(
        self,
        action_name: str,
        *keys
    ):
        """
        Asynchronous variant of `hit`.

        This can be called from the serving thread safely.
        """
        if self.pending is None:
            LOG.error("Pacer is not yet started")
            return
        ev = asyncio.Event()

        await self.pending.async_q.put(
            (ev, action_name, keys)
        )

        await ev.wait()

    def hit(self, action_name, *keys):
        """
        Pace execution, based on the pacing config for the given `action_name`.
        Keys can be included to allow multiple objects
        to be be paced separately on the same action.

        This should not be called from the same thread serving
        the pacing.
        """
        if self.pending is None:
            LOG.error("Pacer is not yet started")
            return
        ev = threading.Event()

        self.pending.sync_q.put(
            (ev, action_name, keys)
        )

        ev.wait()

    def inject_config(self, config: dict):
        """
        Inject settings for pacing
        """
        self.pace_config.update(
            {
                key: (value['max_concurrent'], value['refresh_period'])
                for key, value in config.items()
            }
        )


@dataclass
class PacerWrapper:
    """
    Applies a namespace to various operations related to pacing.
    """
    namespace: str
    pacer: Pacer

    def inject_config(self, napp_config: dict):
        """
        Inject namespace specific settings for pacing
        """
        self.pacer.inject_config(
            {
                self._localized_key(key): value for key, value in napp_config.items()
            }
        )

    def hit(self, action_name, *args, **kwargs):
        """
        Asynchronous variant of `hit`.

        This can be called from the serving thread safely.
        """
        return self.pacer.hit(self._localized_key(action_name), *args, **kwargs)


    async def ahit(self, action_name, *args, **kwargs):
        """
        Pace execution, based on the pacing config for the given `action_name`.
        Keys can be included to allow multiple objects
        to be be paced separately on the same action.

        This should not be called from the same thread serving
        the pacing.
        """
        return await self.pacer.ahit(self._localized_key(action_name), *args, **kwargs)
    
    def _localized_key(self, key):
        return f"{self.namespace}.{key}"
