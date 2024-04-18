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
    pace_config: dict[str, tuple[int, float]]
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
        """Wait until the pacer says the action can occur."""
        if self.pending is None:
            LOG.error("Pacer is not yet started")
            return
        ev = asyncio.Event()

        await self.pending.async_q.put(
            (ev, action_name, keys)
        )

        await ev.wait()

    def hit(self, action_name, *keys):
        """Wait until the pacer says the action can occur."""
        if self.pending is None:
            LOG.error("Pacer is not yet started")
            return
        ev = threading.Event()

        self.pending.sync_q.put(
            (ev, action_name, keys)
        )

        ev.wait()
