from __future__ import annotations

from collections import defaultdict
import inspect
import threading
from threading import Lock
from typing import Hashable, Iterable

import logging

LOG = logging.getLogger(__name__)

class LockGroup:

    __match_args__ = ("name", "lock")

    def __init__(self, name: str, lock: Lock):
        self.name = name
        self.lock = lock
        self.locks = dict[Hashable, tuple[Lock, int]]()
        self.pending_tids = defaultdict[int, set[Hashable]](set)
        self.active_tids = defaultdict[int, set[Hashable]](set)
        self.holders = dict[Hashable, int]()

    def _acquire_helper(self, id: Hashable):
        if id not in self.locks:
            lock, curr_count = Lock(), 0
        else:
            lock, curr_count = self.locks[id]
        self.locks[id] = lock, curr_count + 1
        return lock

    def acquire_element(self, id: Hashable):
        with self.lock:
            lock = self._acquire_helper(id)
            thread_id = threading.get_ident()
            if thread_id in self.active_tids:
                LOG.error(
                    f"Thread {thread_id} is trying to acquire {id!r} from the same lock group {self.name!r} before releasing."
                )
                if id in self.active_tids[thread_id]:
                    LOG.error(
                        f"Thread {thread_id} is already holding lock {id!r} from lock group {self.name!r}."
                    )
                    thread_stack = inspect.stack()[3:]
                    thread_stack_str = '\n'.join([str(frame) for frame in thread_stack])
                    LOG.error(f"Thread {thread_id} stack: {thread_stack_str}")
            self.pending_tids[thread_id].add(id)
        lock.acquire()
        self.holders[id] = thread_id
        with self.lock:
            self.pending_tids[thread_id].remove(id)
            self.active_tids[thread_id].add(id)
            if not self.pending_tids[thread_id]:
                del self.pending_tids[thread_id]

    def acquire_elements(self, ids: Iterable[Hashable]):
        sorted_ids = sorted(ids)
        locks = []
        with self.lock:
            locks = [
                (id, self._acquire_helper(id))
                for id in sorted_ids
            ]
            thread_id = threading.get_ident()
            id_set = set(ids)
            if thread_id in self.active_tids:
                LOG.error(
                    f"Thread {thread_id} is trying to acquire {sorted_ids!r} from the same lock group {self.name!r} before releasing."
                )
                id_intersection = id_set & self.active_tids[thread_id]
                if id_intersection:
                    LOG.error(
                        f"Thread {thread_id} is already holding lock {id_intersection!r} from lock group {self.name!r}."
                    )
            self.pending_tids[thread_id] += id_set
        for id, lock in locks:
            lock.acquire()
            self.holders[id] = thread_id
            with self.lock:
                self.pending_tids[thread_id].remove(id)
                self.active_tids[thread_id].add(id)
                if not self.pending_tids[thread_id]:
                    del self.pending_tids[thread_id]


    def _release_helper(self, id: Hashable):
        lock, curr_count = self.locks[id]
        new_count = curr_count - 1
        if new_count > 0:
            self.locks[id] = lock, new_count
        else:
            del self.locks[id]
        return lock

    def release_element(self, id: Hashable):
        with self.lock:
            lock = self._release_helper(id)
            thread_id = self.holders[id]
            self.active_tids[thread_id].remove(id)
            if not self.active_tids[thread_id]:
                del self.active_tids[thread_id]
        del self.holders[id]
        lock.release()

    def release_elements(self, ids: Iterable[Hashable]):
        sorted_ids = sorted(ids, reverse=True)
        locks = []
        with self.lock:
            locks = [
                (id, self.holders[id], self._release_helper(id))
                for id in sorted_ids
            ]
            for id, thread_id, lock in locks:
                self.active_tids[thread_id].remove(id)
                if not self.active_tids[thread_id]:
                    del self.active_tids[thread_id]
        for id, _, lock in locks:
            del self.holders[id]
            lock.release()
    
    def get_lock(self, id: Hashable) -> LGElement:
        return LGElement(self, id)
    
    def get_multi_lock(self, ids: Iterable[Hashable]) -> MultiLGElement:
        return LGElement(self, ids)
    
    __getitem__ = get_lock

    def __repr__(self):
        return f"LockGroup({self.name}, {self.lock!r})"


class LGElement:
    __match_args__ = ("lock_group", "element_id")

    def __init__(self, lock_group: LockGroup, element_id: Hashable):
        self.lock_group = lock_group
        self.element_id = element_id

    def acquire(self):
        self.lock_group.acquire_element(self.element_id)

    def release(self):
        self.lock_group.release_element(self.element_id)

    def __enter__(self):
        self.acquire()
    
    def __exit__(self, exc_type, exc_val, traceback):
        self.release()

    def __or__(self, value):
        match value:
            case LGElement(other_group, other_id) if other_group == self.lock_group:
                return MultiLGElement(
                    other_group,
                    frozenset({self.element_id, other_id})
                )
            case LGElement(other_group, other_id):
                raise ValueError(
                    f"Tried to combine elements of mismatched lockgroups: {self.lock_group} and {other_group}"
                )
            case MultiLGElement(other_group, other_ids) if other_group == self.lock_group:
                return MultiLGElement(
                    other_group,
                    frozenset({self.element_id}) + other_ids
                )
            case MultiLGElement(other_group, other_ids):
                raise ValueError(
                    f"Tried to combine elements of mismatched lockgroups: {self.lock_group} and {other_group}"
                )
            case _:
                return NotImplemented
            
    def __repr__(self):
        return f"LGElement({self.lock_group!r}, {self.element_id})"

class MultiLGElement:

    __match_args__ = ("lock_group", "element_ids")

    def __init__(self, lock_group: LockGroup, element_ids: Iterable[Hashable]):
        self.lock_group = lock_group
        self.element_ids = frozenset(element_ids)

    def acquire(self):
        self.lock_group.acquire_elements(self.element_ids)

    def release(self):
        self.lock_group.release_elements(self.element_ids)

    def __enter__(self):
        self.acquire()
    
    def __exit__(self, exc_type, exc_val, traceback):
        self.release()

    def __or__(self, value):
        match value:
            case MultiLGElement(other_group, other_ids) if other_group == self.lock_group:
                return MultiLGElement(
                    other_group,
                    self.element_ids + other_ids
                )
            case MultiLGElement(other_group, other_ids):
                raise ValueError(
                    f"Tried to combine elements of mismatched lockgroups: {self.lock_group} and {other_group}"
                )
            case _:
                return NotImplemented
            
    def __repr__(self):
        return f"MultiLGElement({self.lock_group!r}, {self.element_ids})"
