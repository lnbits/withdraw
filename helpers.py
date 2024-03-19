from threading import Lock
from typing import Dict


class CounterLock:
    def __init__(self):
        self.counter = 0
        self.lock = Lock()

    def acquire(self) -> bool:
        self.counter += 1
        return self.lock.acquire()

    def release(self) -> None:
        self.counter -= 1
        return self.lock.release()

    @property
    def no_more_waiters(self) -> bool:
        return self.counter == 0


class NamedLock:
    _lock = Lock()
    _locks: Dict[str, CounterLock] = {}

    def acquire(self, name: str) -> bool:
        self._lock.acquire()

        if name not in self._locks:
            self._locks[name] = CounterLock()

        self._lock.release()

        return self._locks[name].acquire()



    def release(self, name: str):
        self._lock.acquire()

        if name not in self._locks:
            return self._lock.release()

        self._locks[name].release()
        if self._locks[name].no_more_waiters:
            del self._locks[name]

        return self._lock.release()
