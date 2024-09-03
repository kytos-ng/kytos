
import time
from collections import OrderedDict
from logging import LogRecord
from threading import Lock


class RepeateMessageFilter:
    lockout_time: float
    cache_size: int
    _cache: OrderedDict[tuple, float]
    _lock: Lock

    def __init__(self, lockout_time: float, cache_size: int = 512):
        self.lockout_time = lockout_time
        self.cache_size = cache_size
        self._cache = OrderedDict()
        self._lock = Lock()

    def filter(self, record: LogRecord) -> bool:
        key = self._record_key(record)
        current_time = time.time()
        with self._lock:
            if key not in self._cache:
                self._cache[key] = current_time
                if len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
                return True
            elif current_time - self._cache[key] > self.lockout_time:
                self._cache[key] = current_time
                self._cache.move_to_end(key)
                if len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
                return True
            return False

    @staticmethod
    def _record_key(record: LogRecord):
        return (
            record.pathname,
            record.module,
            record.lineno,
            record.levelno,
            record.msg,
            record.args
        )
