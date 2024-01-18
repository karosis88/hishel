import logging
import time
import typing as tp
import warnings
from copy import deepcopy
from pathlib import Path

try:
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore

try:
    import sqlite3
except ImportError:  # pragma: no cover
    sqlite3 = None  # type: ignore

from httpcore import Request, Response
from typing_extensions import TypeAlias

from hishel._serializers import BaseSerializer, clone_model

from .._files import FileManager
from .._s3 import S3Manager
from .._serializers import JSONSerializer, Metadata
from .._synchronization import Lock
from .._utils import float_seconds_to_int_milliseconds

logger = logging.getLogger("hishel.storages")

__all__ = ("FileStorage", "RedisStorage", "SQLiteStorage", "InMemoryStorage", "S3Storage")

StoredResponse: TypeAlias = tp.Tuple[Response, Request, Metadata]

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


class BaseStorage:
    def __init__(
        self,
        serializer: tp.Optional[BaseSerializer] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
    ) -> None:
        self._serializer = serializer or JSONSerializer()
        self._ttl = ttl

    def store(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        raise NotImplementedError()

    def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        raise NotImplementedError()

    def close(self) -> None:
        raise NotImplementedError()


class FileStorage(BaseStorage):
    """
    A simple file storage.

    :param serializer: Serializer capable of serializing and de-serializing http responses, defaults to None
    :type serializer: tp.Optional[BaseSerializer], optional
    :param base_path: A storage base path where the responses should be saved, defaults to None
    :type base_path: tp.Optional[Path], optional
    :param ttl: Specifies the maximum number of seconds that the response can be cached, defaults to None
    :type ttl: tp.Optional[tp.Union[int, float]], optional
    """

    def __init__(
        self,
        serializer: tp.Optional[BaseSerializer] = None,
        base_path: tp.Optional[Path] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
    ) -> None:
        super().__init__(serializer, ttl)

        self._base_path = Path(base_path) if base_path is not None else Path(".cache/hishel")

        if not self._base_path.is_dir():
            self._base_path.mkdir(parents=True)

        self._file_manager = FileManager(is_binary=self._serializer.is_binary)
        self._lock = Lock()

    def store(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Stores the response in the cache.

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

        with self._lock:
            self._file_manager.write_to(
                str(response_path),
                self._serializer.dumps(response=response, request=request, metadata=metadata),
            )
        self._remove_expired_caches()

    def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and his HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        response_path = self._base_path / key

        self._remove_expired_caches()
        with self._lock:
            if response_path.exists():
                return self._serializer.loads(self._file_manager.read_from(str(response_path)))
        return None

    def close(self) -> None:  # pragma: no cover
        return

    def _remove_expired_caches(self) -> None:
        if self._ttl is None:
            return

        with self._lock:
            for file in self._base_path.iterdir():
                if file.is_file():
                    age = time.time() - file.stat().st_mtime
                    if age > self._ttl:
                        file.unlink()


class SQLiteStorage(BaseStorage):
    """
    A simple sqlite3 storage.

    :param serializer: Serializer capable of serializing and de-serializing http responses, defaults to None
    :type serializer: tp.Optional[BaseSerializer], optional
    :param connection: A connection for sqlite, defaults to None
    :type connection: tp.Optional[sqlite3.Connection], optional
    :param ttl: Specifies the maximum number of seconds that the response can be cached, defaults to None
    :type ttl: tp.Optional[tp.Union[int, float]], optional
    """

    def __init__(
        self,
        serializer: tp.Optional[BaseSerializer] = None,
        connection: tp.Optional["sqlite3.Connection"] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
    ) -> None:
        if sqlite3 is None:  # pragma: no cover
            raise RuntimeError(
                (
                    f"The `{type(self).__name__}` was used, but the required packages were not found. "
                    "Check that you have `Hishel` installed with the `sqlite` extension as shown.\n"
                    "```pip install hishel[sqlite]```"
                )
            )
        super().__init__(serializer, ttl)

        self._connection: tp.Optional[sqlite3.Connection] = connection or None
        self._setup_lock = Lock()
        self._setup_completed: bool = False
        self._lock = Lock()

    def _setup(self) -> None:
        with self._setup_lock:
            if not self._setup_completed:
                if not self._connection:  # pragma: no cover
                    self._connection = sqlite3.connect(".hishel.sqlite", check_same_thread=False)
                self._connection.execute(
                    ("CREATE TABLE IF NOT EXISTS cache(key TEXT, data BLOB, date_created REAL)")
                )
                self._connection.commit()
                self._setup_completed = True

    def store(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additioal information about the stored response
        :type metadata: Metadata
        """

        self._setup()
        assert self._connection

        with self._lock:
            self._connection.execute("DELETE FROM cache WHERE key = ?", [key])
            serialized_response = self._serializer.dumps(response=response, request=request, metadata=metadata)
            self._connection.execute(
                "INSERT INTO cache(key, data, date_created) VALUES(?, ?, ?)", [key, serialized_response, time.time()]
            )
            self._connection.commit()
        self._remove_expired_caches()

    def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and its HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        self._setup()
        assert self._connection

        self._remove_expired_caches()
        with self._lock:
            cursor = self._connection.execute("SELECT data FROM cache WHERE key = ?", [key])
            row = cursor.fetchone()
            if row is None:
                return None

            cached_response = row[0]
            return self._serializer.loads(cached_response)

    def close(self) -> None:  # pragma: no cover
        assert self._connection
        self._connection.close()

    def _remove_expired_caches(self) -> None:
        assert self._connection
        if self._ttl is None:
            return

        with self._lock:
            self._connection.execute("DELETE FROM cache WHERE date_created + ? < ?", [self._ttl, time.time()])
            self._connection.commit()


class RedisStorage(BaseStorage):
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
        client: tp.Optional["redis.Redis"] = None,  # type: ignore
        ttl: tp.Optional[tp.Union[int, float]] = None,
    ) -> None:
        if redis is None:  # pragma: no cover
            raise RuntimeError(
                (
                    f"The `{type(self).__name__}` was used, but the required packages were not found. "
                    "Check that you have `Hishel` installed with the `redis` extension as shown.\n"
                    "```pip install hishel[redis]```"
                )
            )
        super().__init__(serializer, ttl)

        if client is None:
            self._client = redis.Redis()  # type: ignore
        else:  # pragma: no cover
            self._client = client

    def store(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additioal information about the stored response
        :type metadata: Metadata
        """

        if self._ttl is not None:
            px = float_seconds_to_int_milliseconds(self._ttl)
        else:
            px = None

        self._client.set(
            key, self._serializer.dumps(response=response, request=request, metadata=metadata), px=px
        )

    def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and its HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        cached_response = self._client.get(key)
        if cached_response is None:
            return None

        return self._serializer.loads(cached_response)

    def close(self) -> None:  # pragma: no cover
        self._client.close()


class InMemoryStorage(BaseStorage):
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
        self._lock = Lock()

    def store(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additioal information about the stored response
        :type metadata: Metadata
        """

        with self._lock:
            response_clone = clone_model(response)
            request_clone = clone_model(request)
            stored_response: StoredResponse = (deepcopy(response_clone), deepcopy(request_clone), metadata)
            self._cache.put(key, (stored_response, time.monotonic()))
        self._remove_expired_caches()

    def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and its HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        self._remove_expired_caches()
        with self._lock:
            try:
                stored_response, _ = self._cache.get(key)
            except KeyError:
                return None
            return stored_response

    def close(self) -> None:  # pragma: no cover
        return

    def _remove_expired_caches(self) -> None:
        if self._ttl is None:
            return

        with self._lock:
            keys_to_remove = set()

            for key in self._cache:
                created_at = self._cache.get(key)[1]

                if time.monotonic() - created_at > self._ttl:
                    keys_to_remove.add(key)

            for key in keys_to_remove:
                self._cache.remove_key(key)


class S3Storage(BaseStorage):  # pragma: no cover
    """
    AWS S3 storage.

    :param serializer: Serializer capable of serializing and de-serializing http responses, defaults to None
    :type serializer: tp.Optional[BaseSerializer], optional
    :param ttl: Specifies the maximum number of seconds that the response can be cached, defaults to None
    :type ttl: tp.Optional[tp.Union[int, float]], optional
    :param client: A client for S3, defaults to None
    :type client: tp.Optional[tp.Any], optional
    """

    def __init__(
        self,
        bucket_name: str,
        serializer: tp.Optional[BaseSerializer] = None,
        ttl: tp.Optional[tp.Union[int, float]] = None,
        client: tp.Optional[tp.Any] = None,
    ) -> None:
        super().__init__(serializer, ttl)

        if boto3 is None:  # pragma: no cover
            raise RuntimeError(
                (
                    f"The `{type(self).__name__}` was used, but the required packages were not found. "
                    "Check that you have `Hishel` installed with the `s3` extension as shown.\n"
                    "```pip install hishel[s3]```"
                )
            )

        self._bucket_name = bucket_name
        client = client or boto3.client("s3")
        self._s3_manager = S3Manager(client=client, bucket_name=bucket_name, is_binary=self._serializer.is_binary)
        self._lock = Lock()

    def store(self, key: str, response: Response, request: Request, metadata: Metadata) -> None:
        """
        Stores the response in the cache.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :param response: An HTTP response
        :type response: httpcore.Response
        :param request: An HTTP request
        :type request: httpcore.Request
        :param metadata: Additioal information about the stored response
        :type metadata: Metadata`
        """

        with self._lock:
            serialized = self._serializer.dumps(response=response, request=request, metadata=metadata)
            self._s3_manager.write_to(path=key, data=serialized)

        self._remove_expired_caches()

    def retrieve(self, key: str) -> tp.Optional[StoredResponse]:
        """
        Retreives the response from the cache using his key.

        :param key: Hashed value of concatenated HTTP method and URI
        :type key: str
        :return: An HTTP response and its HTTP request.
        :rtype: tp.Optional[StoredResponse]
        """

        self._remove_expired_caches()
        with self._lock:
            try:
                return self._serializer.loads(self._s3_manager.read_from(path=key))
            except Exception:
                return None

    def close(self) -> None:  # pragma: no cover
        return

    def _remove_expired_caches(self) -> None:
        if self._ttl is None:
            return

        with self._lock:
            converted_ttl = float_seconds_to_int_milliseconds(self._ttl)
            self._s3_manager.remove_expired(ttl=converted_ttl)
