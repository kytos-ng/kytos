
import time
from logging import LogRecord
from threading import Lock
from typing import Generic, Self, TypeVar

T = TypeVar("T")


class _DoublyLinkedList(Generic[T]):
    value: T
    previous: Self
    next: Self

    def __init__(self, value: T):
        self.value = value
        self.previous = self
        self.next = self

    def swap_next(self, other: Self):

        curr_next = self.next
        other_curr_next = other.next

        self.next = other_curr_next
        other_curr_next.previous = self
        other.next = curr_next
        curr_next.previous = other

    def swap_previous(self, other: Self):
        curr_prev = self.previous
        other_curr_prev = other.previous

        self.previous = other_curr_prev
        other_curr_prev.next = self
        other.previous = curr_prev
        curr_prev.next = other

    def remove(self):
        self.swap_next(self.previous)

    def __iter__(self):
        yield self.value
        curr = self.next
        while curr is not self:
            yield curr.value
            curr = curr.next


K = TypeVar("K")
V = TypeVar("V")


class _LimitedCache(Generic[K, V]):
    root: _DoublyLinkedList[tuple[K, V] | None]
    cache: dict[K, _DoublyLinkedList[tuple[K, V]]]
    max_size: int

    def __init__(self, max_size=512):
        self.root = _DoublyLinkedList(None)
        self.cache = {}
        self.max_size = max_size

    def __getitem__(self, key: K) -> V:
        entry = self.cache[key]
        _, v = entry.value
        return v

    def __contains__(self, key: K) -> bool:
        return key in self.cache

    def __setitem__(self, key: K, value: V):
        if key in self.cache:
            entry = self.cache[key]
            entry.remove()
            entry.value = (key, value)
        else:
            entry = _DoublyLinkedList(
                (key, value)
            )
            self.cache[key] = entry
            if len(self.cache) == self.max_size:
                self._remove_oldest()

        self.root.swap_next(entry)

    def __delitem__(self, key: K):
        entry = self.cache[key]
        del self.cache[key]
        entry.remove()

    def _remove_oldest(self):
        oldest_entry = self.root.previous
        k, _ = oldest_entry.value
        del self.cache[k]
        oldest_entry.remove()


class RepeateMessageFilter:
    lockout_time: float
    _cache: _LimitedCache
    _lock: Lock

    def __init__(self, lockout_time: float, cache_size: int = 512):
        self.lockout_time = lockout_time
        self._cache = _LimitedCache(cache_size)
        self._lock = Lock()

    def filter(self, record: LogRecord) -> bool:
        key = self._record_key(record)
        current_time = time.time()
        with self._lock:
            if key not in self._cache:
                self._cache[key] = current_time
                return True
            elif current_time - self._cache[key] > self.lockout_time:
                self._cache[key] = current_time
                return True
            return False

    @staticmethod
    def _record_key(record: LogRecord):
        return (record.module, record.levelno, record.msg, record.args)
