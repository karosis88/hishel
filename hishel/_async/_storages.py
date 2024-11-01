from __future__ import annotations

import datetime
import logging
import os
import time
import typing as t
import typing as tp
import warnings
from copy import deepcopy
from pathlib import Path

try:
    import boto3

    from .._s3 import AsyncS3Manager
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore

try:
    import anysqlite
except ImportError:  # pragma: no cover
    anysqlite = None  # type: ignore

from httpcore import Request, Response
from typing_extensions import Self, TypeAlias, override

from hishel._serializers import BaseSerializer, clone_model

from .._files import AsyncFileManager
from .._serializers import JSONSerializer, Metadata
from .._synchronization import AsyncLock
from .._utils import float_seconds_to_int_milliseconds

logger = logging.getLogger("hishel.storages")

__all__ = (
    "AsyncBaseStorage",
    "AsyncFileStorage",
    "AsyncRedisStorage",
    "AsyncSQLStorage",
    "AsyncSQLiteStorage",
    "AsyncInMemoryStorage",
    "AsyncS3Storage",
)

StoredResponse: TypeAlias = tp.Tuple[Response, Request, Metadata]
RemoveTypes = tp.Union[str, Response]

try:
    import redis.asyncio as redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


try:
    import sqlalchemy
    import sqlalchemy.ext.asyncio
    import sqlalchemy.orm
except ImportError:  # pragma: no cover
    sqlalchemy = None  # type: ignore


class AsyncBaseStorage:
    def __init__(
        self,
        serializer: tp.Optional[BaseSerializer] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
    ) -> None:
        self._serializer = serializer or JSONSerializer()
        self._ttl = ttl

    async def store(self, key: str, response: Response, request: Request, metadata: Metadata | None = None) -> None:
        raise NotImplementedError()

    async def remove(self, key: RemoveTypes) -> None:
        raise NotImplementedError()

    async def update_metadata(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        raise NotImplementedError()

    async def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        raise NotImplementedError()

    async def aclose(self) -> None:
        raise NotImplementedError()


class AsyncFileStorage(AsyncBaseStorage):
    """
    A simple file storage.

    :param serializer: Serializer capable of serializing and de-serializing http responses, defaults to None
    :type serializer: tp.Optional[BaseSerializer], optional
    :param base_path: A storage base path where the responses should be saved, defaults to None
    :type base_path: tp.Optional[Path], optional
    :param ttl: Specifies the maximum number of seconds that the response can be cached, defaults to None
    :type ttl: tp.Optional[tp.Union[int, float]], optional
    :param check_ttl_every: How often in seconds to check staleness of **all** cache files.
        Makes sense only with set `ttl`, defaults to 60
    :type check_ttl_every: tp.Union[int, float]
    """

    def __init__(
        self,
        serializer: tp.Optional[BaseSerializer] = None,
        base_path: tp.Optional[Path] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
        check_ttl_every: tp.Union[int, float] = 60,
    ) -> None:
        super().__init__(serializer, ttl)

        self._base_path = Path(base_path) if base_path is not None else Path(".cache/hishel")
        self._gitignore_file = self._base_path / ".gitignore"

        if not self._base_path.is_dir():
            self._base_path.mkdir(parents=True)

        if not self._gitignore_file.is_file():
            with open(self._gitignore_file, "w", encoding="utf-8") as f:
                f.write("# Automatically created by Hishel\n*")

        self._file_manager = AsyncFileManager(is_binary=self._serializer.is_binary)
        self._lock = AsyncLock()
        self._check_ttl_every = check_ttl_every
        self._last_cleaned = time.monotonic()

    async def store(self, key: str, response: Response, request: Request, metadata: Metadata | None = None) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additional information about the stored response
        :type metadata: Optional[Metadata]
        """

        metadata = metadata or Metadata(
            cache_key=key, created_at=datetime.datetime.now(datetime.timezone.utc), number_of_uses=0
        )
        response_path = self._base_path / key

        async with self._lock:
            await self._file_manager.write_to(
                str(response_path),
                self._serializer.dumps(response=response, request=request, metadata=metadata),
            )
        await self._remove_expired_caches(response_path)

    async def remove(self, key: RemoveTypes) -> None:
        """
        Removes the response from the cache.

        :param key: Hashed value of concatenated HTTP method and URI or an HTTP response
        :type key: Union[str, Response]
        """

        if isinstance(key, Response):  # pragma: no cover
            key = t.cast(str, key.extensions["cache_metadata"]["cache_key"])

        response_path = self._base_path / key

        async with self._lock:
            if response_path.exists():
                response_path.unlink()

    async def update_metadata(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Updates the metadata of the stored response.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additional information about the stored response
        :type metadata: Metadata
        """
        response_path = self._base_path / key

        async with self._lock:
            if response_path.exists():
                atime = response_path.stat().st_atime
                old_mtime = response_path.stat().st_mtime
                await self._file_manager.write_to(
                    str(response_path),
                    self._serializer.dumps(response=response, request=request, metadata=metadata),
                )

                # Restore the old atime and mtime (we use mtime to check the cache expiration time)
                os.utime(response_path, (atime, old_mtime))
                return

        return await self.store(key, response, request, metadata)  # pragma: no cover

    async def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and his HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        response_path = self._base_path / key

        await self._remove_expired_caches(response_path)
        async with self._lock:
            if response_path.exists():
                read_data = await self._file_manager.read_from(str(response_path))
                if len(read_data) != 0:
                    return self._serializer.loads(read_data)
        return None

    async def aclose(self) -> None:  # pragma: no cover
        return

    async def _remove_expired_caches(self, response_path: Path) -> None:
        if self._ttl is None:
            return

        if time.monotonic() - self._last_cleaned < self._check_ttl_every:
            if response_path.is_file():
                age = time.time() - response_path.stat().st_mtime
                if age > self._ttl:
                    response_path.unlink()
            return

        self._last_cleaned = time.monotonic()
        async with self._lock:
            with os.scandir(self._base_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_file():
                            age = time.time() - entry.stat().st_mtime
                            if age > self._ttl:
                                os.unlink(entry.path)
                    except FileNotFoundError:  # pragma: no cover
                        pass


class AsyncSQLiteStorage(AsyncBaseStorage):
    """
    A simple sqlite3 storage.

    :param serializer: Serializer capable of serializing and de-serializing http responses, defaults to None
    :type serializer: tp.Optional[BaseSerializer], optional
    :param connection: A connection for sqlite, defaults to None
    :type connection: tp.Optional[anysqlite.Connection], optional
    :param ttl: Specifies the maximum number of seconds that the response can be cached, defaults to None
    :type ttl: tp.Optional[tp.Union[int, float]], optional
    """

    def __init__(
        self,
        serializer: tp.Optional[BaseSerializer] = None,
        connection: tp.Optional[anysqlite.Connection] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
    ) -> None:
        if anysqlite is None:  # pragma: no cover
            raise RuntimeError(
                f"The `{type(self).__name__}` was used, but the required packages were not found. "
                "Check that you have `Hishel` installed with the `sqlite` extension as shown.\n"
                "```pip install hishel[sqlite]```"
            )
        super().__init__(serializer, ttl)

        self._connection: tp.Optional[anysqlite.Connection] = connection or None
        self._setup_lock = AsyncLock()
        self._setup_completed: bool = False
        self._lock = AsyncLock()

    async def _setup(self) -> None:
        async with self._setup_lock:
            if not self._setup_completed:
                if not self._connection:  # pragma: no cover
                    self._connection = await anysqlite.connect(".hishel.sqlite", check_same_thread=False)
                await self._connection.execute(
                    "CREATE TABLE IF NOT EXISTS cache(key TEXT, data BLOB, date_created REAL)"
                )
                await self._connection.commit()
                self._setup_completed = True

    async def store(self, key: str, response: Response, request: Request, metadata: Metadata | None = None) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additioal information about the stored response
        :type metadata: Optional[Metadata]
        """

        await self._setup()
        assert self._connection

        metadata = metadata or Metadata(
            cache_key=key, created_at=datetime.datetime.now(datetime.timezone.utc), number_of_uses=0
        )

        async with self._lock:
            await self._connection.execute("DELETE FROM cache WHERE key = ?", [key])
            serialized_response = self._serializer.dumps(response=response, request=request, metadata=metadata)
            await self._connection.execute(
                "INSERT INTO cache(key, data, date_created) VALUES(?, ?, ?)", [key, serialized_response, time.time()]
            )
            await self._connection.commit()
        await self._remove_expired_caches()

    async def remove(self, key: RemoveTypes) -> None:
        """
        Removes the response from the cache.

        :param key: Hashed value of concatenated HTTP method and URI or an HTTP response
        :type key: Union[str, Response]
        """

        await self._setup()
        assert self._connection

        if isinstance(key, Response):  # pragma: no cover
            key = t.cast(str, key.extensions["cache_metadata"]["cache_key"])

        async with self._lock:
            await self._connection.execute("DELETE FROM cache WHERE key = ?", [key])
            await self._connection.commit()

    async def update_metadata(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Updates the metadata of the stored response.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additional information about the stored response
        :type metadata: Metadata
        """

        await self._setup()
        assert self._connection

        async with self._lock:
            cursor = await self._connection.execute("SELECT data FROM cache WHERE key = ?", [key])
            row = await cursor.fetchone()
            if row is not None:
                serialized_response = self._serializer.dumps(response=response, request=request, metadata=metadata)
                await self._connection.execute("UPDATE cache SET data = ? WHERE key = ?", [serialized_response, key])
                await self._connection.commit()
                return
        return await self.store(key, response, request, metadata)  # pragma: no cover

    async def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and its HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        await self._setup()
        assert self._connection

        await self._remove_expired_caches()
        async with self._lock:
            cursor = await self._connection.execute("SELECT data FROM cache WHERE key = ?", [key])
            row = await cursor.fetchone()
            if row is None:
                return None

            cached_response = row[0]
            return self._serializer.loads(cached_response)

    async def aclose(self) -> None:  # pragma: no cover
        if self._connection is not None:
            await self._connection.close()

    async def _remove_expired_caches(self) -> None:
        assert self._connection
        if self._ttl is None:
            return

        async with self._lock:
            await self._connection.execute("DELETE FROM cache WHERE date_created + ? < ?", [self._ttl, time.time()])
            await self._connection.commit()


class AsyncRedisStorage(AsyncBaseStorage):
    """
    A simple redis storage.

    :param serializer: Serializer capable of serializing and de-serializing http responses, defaults to None
    :type serializer: tp.Optional[BaseSerializer], optional
    :param client: A client for redis, defaults to None
    :type client: tp.Optional["redis.Redis"], optional
    :param ttl: Specifies the maximum number of seconds that the response can be cached, defaults to None
    :type ttl: tp.Optional[tp.Union[int, float]], optional
    """

    def __init__(
        self,
        serializer: tp.Optional[BaseSerializer] = None,
        client: tp.Optional[redis.Redis] = None,  # type: ignore
        ttl: tp.Optional[tp.Union[int, float]] = None,
    ) -> None:
        if redis is None:  # pragma: no cover
            raise RuntimeError(
                f"The `{type(self).__name__}` was used, but the required packages were not found. "
                "Check that you have `Hishel` installed with the `redis` extension as shown.\n"
                "```pip install hishel[redis]```"
            )
        super().__init__(serializer, ttl)

        if client is None:
            self._client = redis.Redis()  # type: ignore
        else:  # pragma: no cover
            self._client = client

    async def store(self, key: str, response: Response, request: Request, metadata: Metadata | None = None) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additioal information about the stored response
        :type metadata: Optional[Metadata]
        """

        metadata = metadata or Metadata(
            cache_key=key, created_at=datetime.datetime.now(datetime.timezone.utc), number_of_uses=0
        )

        if self._ttl is not None:
            px = float_seconds_to_int_milliseconds(self._ttl)
        else:
            px = None

        await self._client.set(
            key, self._serializer.dumps(response=response, request=request, metadata=metadata), px=px
        )

    async def remove(self, key: RemoveTypes) -> None:
        """
        Removes the response from the cache.

        :param key: Hashed value of concatenated HTTP method and URI or an HTTP response
        :type key: Union[str, Response]
        """

        if isinstance(key, Response):  # pragma: no cover
            key = t.cast(str, key.extensions["cache_metadata"]["cache_key"])

        await self._client.delete(key)

    async def update_metadata(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Updates the metadata of the stored response.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additional information about the stored response
        :type metadata: Metadata
        """

        ttl_in_milliseconds = await self._client.pttl(key)

        # -2: if the key does not exist in Redis
        # -1: if the key exists in Redis but has no expiration
        if ttl_in_milliseconds == -2 or ttl_in_milliseconds == -1:  # pragma: no cover
            await self.store(key, response, request, metadata)
        else:
            await self._client.set(
                key,
                self._serializer.dumps(response=response, request=request, metadata=metadata),
                px=ttl_in_milliseconds,
            )

    async def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and its HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        cached_response = await self._client.get(key)
        if cached_response is None:
            return None

        return self._serializer.loads(cached_response)

    async def aclose(self) -> None:  # pragma: no cover
        await self._client.close()


class AsyncInMemoryStorage(AsyncBaseStorage):
    """
    A simple in-memory storage.

    :param serializer: Serializer capable of serializing and de-serializing http responses, defaults to None
    :type serializer: tp.Optional[BaseSerializer], optional
    :param ttl: Specifies the maximum number of seconds that the response can be cached, defaults to None
    :type ttl: tp.Optional[tp.Union[int, float]], optional
    :param capacity: The maximum number of responses that can be cached, defaults to 128
    :type capacity: int, optional
    """

    def __init__(
        self,
        serializer: tp.Optional[BaseSerializer] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
        capacity: int = 128,
    ) -> None:
        super().__init__(serializer, ttl)

        if serializer is not None:  # pragma: no cover
            warnings.warn("The serializer is not used in the in-memory storage.", RuntimeWarning)

        from hishel import LFUCache

        self._cache: LFUCache[str, tp.Tuple[StoredResponse, float]] = LFUCache(capacity=capacity)
        self._lock = AsyncLock()

    async def store(self, key: str, response: Response, request: Request, metadata: Metadata | None = None) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additioal information about the stored response
        :type metadata: Optional[Metadata]
        """

        metadata = metadata or Metadata(
            cache_key=key, created_at=datetime.datetime.now(datetime.timezone.utc), number_of_uses=0
        )

        async with self._lock:
            response_clone = clone_model(response)
            request_clone = clone_model(request)
            stored_response: StoredResponse = (deepcopy(response_clone), deepcopy(request_clone), metadata)
            self._cache.put(key, (stored_response, time.monotonic()))
        await self._remove_expired_caches()

    async def remove(self, key: RemoveTypes) -> None:
        """
        Removes the response from the cache.

        :param key: Hashed value of concatenated HTTP method and URI or an HTTP response
        :type key: Union[str, Response]
        """

        if isinstance(key, Response):  # pragma: no cover
            key = t.cast(str, key.extensions["cache_metadata"]["cache_key"])

        async with self._lock:
            self._cache.remove_key(key)

    async def update_metadata(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Updates the metadata of the stored response.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additional information about the stored response
        :type metadata: Metadata
        """

        async with self._lock:
            try:
                stored_response, created_at = self._cache.get(key)
                stored_response = (stored_response[0], stored_response[1], metadata)
                self._cache.put(key, (stored_response, created_at))
                return
            except KeyError:  # pragma: no cover
                pass
        await self.store(key, response, request, metadata)  # pragma: no cover

    async def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and its HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        await self._remove_expired_caches()
        async with self._lock:
            try:
                stored_response, _ = self._cache.get(key)
            except KeyError:
                return None
            return stored_response

    async def aclose(self) -> None:  # pragma: no cover
        return

    async def _remove_expired_caches(self) -> None:
        if self._ttl is None:
            return

        async with self._lock:
            keys_to_remove = set()

            for key in self._cache:
                created_at = self._cache.get(key)[1]

                if time.monotonic() - created_at > self._ttl:
                    keys_to_remove.add(key)

            for key in keys_to_remove:
                self._cache.remove_key(key)


class AsyncS3Storage(AsyncBaseStorage):  # pragma: no cover
    """
    AWS S3 storage.

    :param bucket_name: The name of the bucket to store the responses in
    :type bucket_name: str
    :param serializer: Serializer capable of serializing and de-serializing http responses, defaults to None
    :type serializer: tp.Optional[BaseSerializer], optional
    :param ttl: Specifies the maximum number of seconds that the response can be cached, defaults to None
    :type ttl: tp.Optional[tp.Union[int, float]], optional
    :param check_ttl_every: How often in seconds to check staleness of **all** cache files.
        Makes sense only with set `ttl`, defaults to 60
    :type check_ttl_every: tp.Union[int, float]
    :param client: A client for S3, defaults to None
    :type client: tp.Optional[tp.Any], optional
    """

    def __init__(
        self,
        bucket_name: str,
        serializer: tp.Optional[BaseSerializer] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
        check_ttl_every: tp.Union[int, float] = 60,
        client: tp.Optional[tp.Any] = None,
    ) -> None:
        super().__init__(serializer, ttl)

        if boto3 is None:  # pragma: no cover
            raise RuntimeError(
                f"The `{type(self).__name__}` was used, but the required packages were not found. "
                "Check that you have `Hishel` installed with the `s3` extension as shown.\n"
                "```pip install hishel[s3]```"
            )

        self._bucket_name = bucket_name
        client = client or boto3.client("s3")
        self._s3_manager = AsyncS3Manager(
            client=client,
            bucket_name=bucket_name,
            is_binary=self._serializer.is_binary,
            check_ttl_every=check_ttl_every,
        )
        self._lock = AsyncLock()

    async def store(self, key: str, response: Response, request: Request, metadata: Metadata | None = None) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additioal information about the stored response
        :type metadata: Optional[Metadata]`
        """

        metadata = metadata or Metadata(
            cache_key=key, created_at=datetime.datetime.now(datetime.timezone.utc), number_of_uses=0
        )

        async with self._lock:
            serialized = self._serializer.dumps(response=response, request=request, metadata=metadata)
            await self._s3_manager.write_to(path=key, data=serialized)

        await self._remove_expired_caches(key)

    async def remove(self, key: RemoveTypes) -> None:
        """
        Removes the response from the cache.

        :param key: Hashed value of concatenated HTTP method and URI or an HTTP response
        :type key: Union[str, Response]
        """

        if isinstance(key, Response):  # pragma: no cover
            key = t.cast(str, key.extensions["cache_metadata"]["cache_key"])

        async with self._lock:
            await self._s3_manager.remove_entry(key)

    async def update_metadata(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Updates the metadata of the stored response.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additional information about the stored response
        :type metadata: Metadata
        """

        async with self._lock:
            serialized = self._serializer.dumps(response=response, request=request, metadata=metadata)
            await self._s3_manager.write_to(path=key, data=serialized, only_metadata=True)

    async def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and its HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        await self._remove_expired_caches(key)
        async with self._lock:
            try:
                return self._serializer.loads(await self._s3_manager.read_from(path=key))
            except Exception:
                return None

    async def aclose(self) -> None:  # pragma: no cover
        return

    async def _remove_expired_caches(self, key: str) -> None:
        if self._ttl is None:
            return

        async with self._lock:
            converted_ttl = float_seconds_to_int_milliseconds(self._ttl)
            await self._s3_manager.remove_expired(ttl=converted_ttl, key=key)


class AsyncSQLStorage(AsyncBaseStorage):
    def __init__(
        self: Self,
        engine: sqlalchemy.ext.asyncio.AsyncEngine,
        serializer: tp.Optional[BaseSerializer] = None,
        ttl: tp.Optional[datetime.timedelta] = None,
        max_id_len: int = 1024,
        max_data_size_in_bytes: int = 1_048_576,  # 1MB
    ) -> None:
        if sqlalchemy is None:
            raise RuntimeError(
                f"The `{type(self).__name__}` was used, but the required packages were not found. "
                "Check that you have `Hishel` installed with the `sql` extension as shown.\n"
                "```pip install hishel[sql]```"
            )  # pragma: no cover
        super().__init__(
            serializer=serializer,
            ttl=ttl.total_seconds() if isinstance(ttl, datetime.timedelta) else ttl,
        )
        self._engine: sqlalchemy.ext.asyncio.AsyncEngine = engine
        self._has_done_setup: bool = False
        self._lock: AsyncLock = AsyncLock()
        self._ttl_as_timedelta: tp.Optional[datetime.timedelta] = ttl

        class Base(sqlalchemy.ext.asyncio.AsyncAttrs, sqlalchemy.orm.DeclarativeBase):
            pass

        class Cache(Base):
            __tablename__ = "cache"
            id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
                sqlalchemy.String(max_id_len),
                primary_key=True,
            )
            data: sqlalchemy.orm.Mapped[bytes] = sqlalchemy.orm.mapped_column(
                sqlalchemy.BLOB(max_data_size_in_bytes),
            )
            date_created: sqlalchemy.orm.Mapped[float] = sqlalchemy.orm.mapped_column(
                sqlalchemy.Float(),
            )

        self._cache_cls = Cache
        self._base = Base

    @override
    async def store(
        self: Self,
        key: str,
        response: Response,
        request: Request,
        metadata: Metadata | None = None,
    ) -> None:
        await self._setup()
        metadata = metadata or Metadata(
            cache_key=key,
            created_at=datetime.datetime.now(datetime.timezone.utc),
            number_of_uses=0,
        )

        async with sqlalchemy.ext.asyncio.AsyncSession(self._engine) as session:
            async with session.begin():
                await self._clear_cache(key=key, session=session)
                serialized_response = self._serialize_data(
                    response=response,
                    request=request,
                    metadata=metadata,
                )
                session.add(
                    self._cache_cls(
                        id=key,
                        data=serialized_response,
                        date_created=metadata["created_at"].timestamp(),
                    ),
                )

    @override
    async def update_metadata(
        self: Self,
        key: str,
        response: Response,
        request: Request,
        metadata: Metadata,
    ) -> None:
        await self._setup()  # pragma: no cover

        async with sqlalchemy.ext.asyncio.AsyncSession(self._engine) as session:  # pragma: no cover
            async with session.begin():  # pragma: no cover
                row = await self._get_from_db(key=key, session=session)  # pragma: no cover
                if row is not None:  # pragma: no cover
                    row.data = self._serialize_data(
                        response=response,
                        request=request,
                        metadata=metadata,
                    )  # pragma: no cover
                    session.add(row)  # pragma: no cover
                    return  # pragma: no cover
        return await self.store(key, response, request, metadata)  # pragma: no cover

    @override
    async def retrieve(
        self: Self,
        key: str,
    ) -> tp.Optional[StoredResponse]:
        await self._setup()
        async with sqlalchemy.ext.asyncio.AsyncSession(self._engine) as session:
            async with session.begin():
                await self._clear_cache(key=key, session=session)
            result = await (
                await session.stream_scalars(
                    sqlalchemy.select(self._cache_cls).where(
                        self._cache_cls.id == key,
                    )
                )
            ).one_or_none()
        if result is None:
            return None
        return self._deserialize_data(result.data)

    @override
    async def remove(self: Self, key: RemoveTypes) -> None:
        """
        Removes the response from the cache.

        :param key: Hashed value of concatenated HTTP method and URI or an HTTP response
        :type key: Union[str, Response]
        """
        await self._setup()

        if isinstance(key, Response):  # pragma: no cover
            key = t.cast(str, key.extensions["cache_metadata"]["cache_key"])

        async with sqlalchemy.ext.asyncio.AsyncSession(self._engine) as session:
            async with session.begin():
                delete_item_stmt = sqlalchemy.delete(self._cache_cls).where(self._cache_cls.id == key)
                await session.execute(delete_item_stmt)

    @override
    async def aclose(self: Self) -> None:
        pass  # pragma: no cover

    async def _setup(self: Self) -> None:
        if self._has_done_setup:
            return
        async with self._lock, self._engine.begin() as conn:
            await conn.run_sync(self._base.metadata.create_all)
            self._has_done_setup = True

    async def _clear_cache(
        self: Self,
        key: str,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> None:
        if self._ttl_as_timedelta is None:
            return
        delete_statement = (
            sqlalchemy.delete(self._cache_cls)
            .where(self._cache_cls.id == key)
            .where(
                self._cache_cls.date_created + self._ttl_as_timedelta.total_seconds()
                < datetime.datetime.now(tz=datetime.timezone.utc).timestamp()
            )
        )
        await session.execute(delete_statement)

    async def _get_from_db(
        self: Self,
        key: str,
        session: sqlalchemy.ext.asyncio.AsyncSession,
    ) -> tp.Optional[tp.Any]:
        await self._clear_cache(key=key, session=session)  # pragma: no cover
        return await (
            await session.stream_scalars(
                sqlalchemy.select(self._cache_cls).where(
                    self._cache_cls.id == key,
                )
            )
        ).one_or_none()  # pragma: no cover

    # I need to serialize / deserialize as it can handle only bytes.

    def _serialize_data(
        self: Self,
        response: Response,
        request: Request,
        metadata: Metadata,
    ) -> bytes:
        serialized_data = self._serializer.dumps(response=response, request=request, metadata=metadata)
        if isinstance(serialized_data, str):
            return serialized_data.encode("utf-8")
        return serialized_data  # pragma: no cover

    def _deserialize_data(
        self: Self,
        data: bytes,
    ) -> tp.Tuple[Response, Request, Metadata]:
        try:
            cleaned_data: tp.Union[str, bytes] = data.decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover
            cleaned_data = data  # pragma: no cover
        return self._serializer.loads(cleaned_data)
