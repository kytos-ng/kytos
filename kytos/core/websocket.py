"""WebSocket abstraction."""
import logging
from janus import Queue

__all__ = ("WebSocketHandler",)


class WebSocketHandler:
    """Log handler that logs to web socket."""

    queues: list[Queue] = []

    @classmethod
    def get_handler(cls):
        """Output logs to a web socket, filtering unwanted messages."""
        stream = WebSocketQueueStream()
        handler = logging.StreamHandler(stream)
        handler.addFilter(cls._filter_web_requests)
        return handler

    @staticmethod
    def _filter_web_requests(record):
        """Only allow web server messages with level higher than info.

        Do not print web requests (INFO level) to avoid infinite loop when
        printing the logs in the web interface with long-polling mode.
        """
        # print(f"fox name: {record.name}")
        # TODO
        return True
        if record.name.startswith("uvicorn") and  \
           record.levelno >= logging.INFO:
            return False
        return True

    @classmethod
    def subcribe(cls, queue: Queue) -> None:
        """Subcribe a queue."""
        cls.queues.append(queue)

    @classmethod
    def unsubscribe(cls, queue: Queue) -> None:
        """Unsubscribe a queue."""
        try:
            cls.queues.remove(queue)
        except ValueError:
            pass

    @classmethod
    def publish(cls, lines: list[str]) -> None:
        """Publish to consumer queues."""
        for queue in cls.queues:
            queue.sync_q.put_nowait(lines)


class WebSocketQueueStream:
    """WebSocketQueueStream."""

    def __init__(self):
        """Constructor."""
        self._content = ""

    def write(self, content):
        """Store a new line."""
        self._content += content

    def flush(self):
        """Send lines and reset the content."""
        lines = self._content.split("\n")[:-1]
        self._content = ""
        WebSocketHandler.publish(lines)
