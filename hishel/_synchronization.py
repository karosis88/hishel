from __future__ import annotations

import types
import typing as tp
from threading import Lock as T_LOCK

import anyio


class AsyncLock:
    def __init__(self) -> None:
        self._lock = anyio.Lock()

    async def __aenter__(self) -> None:
        await self._lock.acquire()

    async def __aexit__(
        self,
        exc_type: tp.Type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: types.TracebackType | None = None,
    ) -> None:
        self._lock.release()


class Lock:
    def __init__(self) -> None:
        self._lock = T_LOCK()

    def __enter__(self) -> None:
        self._lock.acquire()

    def __exit__(
        self,
        exc_type: tp.Type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: types.TracebackType | None = None,
    ) -> None:
        self._lock.release()
