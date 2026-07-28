"""Active query registry for cancellation support."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.core.exceptions import QueryCancelledError

logger = logging.getLogger("pi_analytics_data.service.query_registry")


@dataclass
class ActiveQuery:
    query_id: str
    started_at: float = field(default_factory=time.monotonic)
    cancelled: bool = False
    main_task: Optional[asyncio.Task] = None
    http_tasks: Set[asyncio.Task] = field(default_factory=set)
    pi_request_count: int = 0


class QueryRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active: Dict[str, ActiveQuery] = {}

    async def register(
        self,
        query_id: str,
        main_task: Optional[asyncio.Task] = None,
    ) -> ActiveQuery:
        async with self._lock:
            if query_id in self._active:
                return self._active[query_id]
            entry = ActiveQuery(query_id=query_id, main_task=main_task)
            self._active[query_id] = entry
            logger.info("Query %s registered", query_id)
            return entry

    async def unregister(self, query_id: str) -> None:
        async with self._lock:
            self._active.pop(query_id, None)
            logger.info("Query %s unregistered", query_id)

    async def cancel(self, query_id: str) -> bool:
        async with self._lock:
            entry = self._active.get(query_id)
            if entry is None:
                return False
            if entry.cancelled:
                return True
            entry.cancelled = True
            elapsed = time.monotonic() - entry.started_at
            logger.info(
                "Query %s cancelled after %.1fs (%d PI requests)",
                query_id, elapsed, entry.pi_request_count,
            )
            if entry.main_task is not None and not entry.main_task.done():
                entry.main_task.cancel()
            for t in entry.http_tasks:
                if not t.done():
                    t.cancel()
            entry.http_tasks.clear()
            return True

    async def check_cancelled(self, query_id: str) -> None:
        async with self._lock:
            entry = self._active.get(query_id)
            if entry is not None and entry.cancelled:
                raise QueryCancelledError(
                    f"Consulta {query_id} foi cancelada."
                )

    async def register_http_task(
        self, query_id: str, task: asyncio.Task
    ) -> None:
        async with self._lock:
            entry = self._active.get(query_id)
            if entry is not None:
                entry.http_tasks.add(task)

    async def unregister_http_task(
        self, query_id: str, task: asyncio.Task
    ) -> None:
        async with self._lock:
            entry = self._active.get(query_id)
            if entry is not None:
                entry.http_tasks.discard(task)

    async def increment_pi_requests(self, query_id: str) -> int:
        async with self._lock:
            entry = self._active.get(query_id)
            if entry is not None:
                entry.pi_request_count += 1
                return entry.pi_request_count
            return 0

    async def get_pi_request_count(self, query_id: str) -> int:
        async with self._lock:
            entry = self._active.get(query_id)
            return entry.pi_request_count if entry is not None else 0

    async def is_cancelled(self, query_id: str) -> bool:
        async with self._lock:
            entry = self._active.get(query_id)
            return entry is not None and entry.cancelled

    async def clear(self) -> None:
        async with self._lock:
            for entry in self._active.values():
                if entry.main_task is not None and not entry.main_task.done():
                    entry.main_task.cancel()
                for t in entry.http_tasks:
                    if not t.done():
                        t.cancel()
            self._active.clear()

    @property
    def active_count(self) -> int:
        return len(self._active)


_query_registry = QueryRegistry()


def get_query_registry() -> QueryRegistry:
    return _query_registry
