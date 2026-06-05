from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, Sequence


DEFAULT_TDX_SERVERS: tuple[tuple[str, int], ...] = (
    ("119.147.212.81", 7709),
    ("221.194.181.176", 7709),
    ("202.108.253.130", 7709),
    ("59.173.18.69", 7709),
    ("180.153.18.170", 7709),
    ("218.75.126.9", 7709),
)


def parse_tdx_servers(raw: str | Sequence[str | tuple[str, int]] | None) -> tuple[tuple[str, int], ...]:
    if raw is None:
        return DEFAULT_TDX_SERVERS
    items: Sequence[str | tuple[str, int]]
    if isinstance(raw, str):
        items = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        items = raw
    servers: list[tuple[str, int]] = []
    for item in items:
        if isinstance(item, tuple):
            host, port = item
            servers.append((str(host), int(port)))
            continue
        host, _, port_text = str(item).partition(":")
        if not host:
            continue
        servers.append((host, int(port_text or 7709)))
    return tuple(servers or DEFAULT_TDX_SERVERS)


@dataclass
class TdxPoolSnapshot:
    server: str
    port: int
    slot_index: int
    successes: int
    failures: int
    consecutive_failures: int
    cooldown_until: float
    last_latency_seconds: float | None


@dataclass
class _TdxSlot:
    server: tuple[str, int]
    slot_index: int
    semaphore: threading.BoundedSemaphore = field(default_factory=lambda: threading.BoundedSemaphore(1))
    client: object | None = None
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_latency_seconds: float | None = None


class TdxServerPool:
    def __init__(
        self,
        servers: Sequence[str | tuple[str, int]] | str | None = None,
        per_server_workers: int = 1,
        cooldown_seconds: float = 120.0,
        failure_threshold: int = 3,
        acquire_timeout_seconds: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        parsed = parse_tdx_servers(servers)
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.failure_threshold = max(1, int(failure_threshold))
        self.acquire_timeout_seconds = max(0.1, float(acquire_timeout_seconds))
        self._clock = clock
        self._sleeper = sleeper
        self._slots = [
            _TdxSlot(server=server, slot_index=slot_index)
            for server in parsed
            for slot_index in range(max(1, int(per_server_workers or 1)))
        ]
        self._lock = threading.Lock()
        self._cursor = 0

    def _available_slot(self) -> _TdxSlot | None:
        now = self._clock()
        with self._lock:
            total = len(self._slots)
            for offset in range(total):
                index = (self._cursor + offset) % total
                slot = self._slots[index]
                if slot.cooldown_until > now:
                    continue
                if slot.semaphore.acquire(blocking=False):
                    self._cursor = (index + 1) % total
                    return slot
        return None

    def acquire(self) -> _TdxSlot:
        deadline = self._clock() + self.acquire_timeout_seconds
        while self._clock() <= deadline:
            slot = self._available_slot()
            if slot is not None:
                return slot
            self._sleeper(0.05)
        raise TimeoutError("TDX server pool has no available connection slot")

    def record_success(self, slot: _TdxSlot, latency_seconds: float) -> None:
        with self._lock:
            slot.successes += 1
            slot.consecutive_failures = 0
            slot.last_latency_seconds = latency_seconds

    def record_failure(self, slot: _TdxSlot, latency_seconds: float) -> None:
        with self._lock:
            slot.failures += 1
            slot.consecutive_failures += 1
            slot.last_latency_seconds = latency_seconds
            if slot.consecutive_failures >= self.failure_threshold:
                slot.cooldown_until = self._clock() + self.cooldown_seconds

    @contextmanager
    def lease(self) -> Iterator[_TdxSlot]:
        slot = self.acquire()
        start = self._clock()
        try:
            yield slot
        except Exception:
            self.record_failure(slot, self._clock() - start)
            raise
        else:
            self.record_success(slot, self._clock() - start)
        finally:
            slot.semaphore.release()

    def get_or_create_client(self, slot: _TdxSlot, factory: Callable[[tuple[str, int]], object]) -> object:
        if slot.client is None:
            slot.client = factory(slot.server)
        return slot.client

    def snapshots(self) -> list[TdxPoolSnapshot]:
        with self._lock:
            return [
                TdxPoolSnapshot(
                    server=slot.server[0],
                    port=slot.server[1],
                    slot_index=slot.slot_index,
                    successes=slot.successes,
                    failures=slot.failures,
                    consecutive_failures=slot.consecutive_failures,
                    cooldown_until=slot.cooldown_until,
                    last_latency_seconds=slot.last_latency_seconds,
                )
                for slot in self._slots
            ]
