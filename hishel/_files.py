from __future__ import annotations

from typing import cast

import anyio


class AsyncBaseFileManager:
    def __init__(self, is_binary: bool) -> None:
        self.is_binary = is_binary

    async def write_to(self, path: str, data: bytes | str, is_binary: bool | None = None) -> None:
        raise NotImplementedError()

    async def read_from(self, path: str, is_binary: bool | None = None) -> bytes | str:
        raise NotImplementedError()


class AsyncFileManager(AsyncBaseFileManager):
    async def write_to(self, path: str, data: bytes | str, is_binary: bool | None = None) -> None:
        is_binary = self.is_binary if is_binary is None else is_binary
        mode = "wb" if is_binary else "wt"
        async with await anyio.open_file(path, mode) as f:  # type: ignore[call-overload]
            await f.write(data)

    async def read_from(self, path: str, is_binary: bool | None = None) -> bytes | str:
        is_binary = self.is_binary if is_binary is None else is_binary

        async with await anyio.open_file(path, "rb" if is_binary else "rt") as f:  # type: ignore[call-overload]
            return await f.read()


class BaseFileManager:
    def __init__(self, is_binary: bool) -> None:
        self.is_binary = is_binary

    def write_to(self, path: str, data: bytes | str, is_binary: bool | None = None) -> None:
        raise NotImplementedError()

    def read_from(self, path: str, is_binary: bool | None = None) -> bytes | str:
        raise NotImplementedError()


class FileManager(BaseFileManager):
    def write_to(self, path: str, data: bytes | str, is_binary: bool | None = None) -> None:
        is_binary = self.is_binary if is_binary is None else is_binary
        mode = "wb" if is_binary else "wt"
        with open(path, mode) as f:
            f.write(data)

    def read_from(self, path: str, is_binary: bool | None = None) -> bytes | str:
        is_binary = self.is_binary if is_binary is None else is_binary
        with open(path, "rb" if is_binary else "rt") as f:
            result = f.read()
            return cast(bytes, result) if is_binary else cast(str, result)
