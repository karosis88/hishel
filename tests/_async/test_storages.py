import datetime
import os
from pathlib import Path

import anysqlite
import pytest
from httpcore import Request, Response

from hishel import AsyncFileStorage, AsyncInMemoryStorage, AsyncRedisStorage, AsyncSQLiteStorage, AsyncSQLStorage
from hishel._serializers import Metadata
from hishel._utils import asleep, generate_key

dummy_metadata = Metadata(cache_key="test", number_of_uses=0, created_at=datetime.datetime.now(datetime.timezone.utc))


async def is_redis_down() -> bool:
    import redis.asyncio as redis

    connection = redis.Redis()
    try:
        return not await connection.ping()
    except BaseException:  # pragma: no cover
        return True


@pytest.mark.anyio
async def test_filestorage(use_temp_dir):
    storage = AsyncFileStorage()

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(key, response=response, request=request, metadata=dummy_metadata)

    stored_data = await storage.retrieve(key)
    assert stored_data is not None
    stored_response, stored_request, metadata = stored_data
    stored_response.read()
    assert isinstance(stored_response, Response)
    assert stored_response.status == 200
    assert stored_response.headers == []
    assert stored_response.content == b"test"


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_redisstorage(anyio_backend):
    if await is_redis_down():  # pragma: no cover
        pytest.fail("Redis server was not found")
    storage = AsyncRedisStorage()

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(key, response=response, request=request, metadata=dummy_metadata)

    stored_data = await storage.retrieve(key)
    assert stored_data is not None
    stored_response, stored_request, metadata = stored_data
    stored_response.read()
    assert isinstance(stored_response, Response)
    assert stored_response.status == 200
    assert stored_response.headers == []
    assert stored_response.content == b"test"


@pytest.mark.anyio
async def test_sqlitestorage():
    storage = AsyncSQLiteStorage(connection=await anysqlite.connect(":memory:"))

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(key, response=response, request=request, metadata=dummy_metadata)

    stored_data = await storage.retrieve(key)
    assert stored_data is not None
    stored_response, stored_request, metadata = stored_data
    stored_response.read()
    assert isinstance(stored_response, Response)
    assert stored_response.status == 200
    assert stored_response.headers == []
    assert stored_response.content == b"test"


@pytest.mark.anyio
async def test_inmemorystorage():
    storage = AsyncInMemoryStorage()

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(key, response=response, request=request, metadata=dummy_metadata)

    stored_data = await storage.retrieve(key)
    assert stored_data is not None
    stored_response, stored_request, metadata = stored_data
    stored_response.read()
    assert isinstance(stored_response, Response)
    assert stored_response.status == 200
    assert stored_response.headers == []
    assert stored_response.content == b"test"


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_filestorage_expired(use_temp_dir, anyio_backend):
    storage = AsyncFileStorage(ttl=0.2, check_ttl_every=0.1)
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert await storage.retrieve(first_key) is not None

    await asleep(0.3)
    await storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)

    assert await storage.retrieve(first_key) is None


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_filestorage_timer(use_temp_dir, anyio_backend):
    storage = AsyncFileStorage(ttl=0.2, check_ttl_every=0.2)

    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert await storage.retrieve(first_key) is not None
    await asleep(0.1)
    assert await storage.retrieve(first_key) is not None
    await storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)
    assert await storage.retrieve(second_key) is not None
    await asleep(0.1)
    assert await storage.retrieve(first_key) is None
    assert await storage.retrieve(second_key) is not None
    await asleep(0.1)
    assert await storage.retrieve(second_key) is None


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_filestorage_ttl_after_hits(use_temp_dir, anyio_backend):
    storage = AsyncFileStorage(ttl=0.2, check_ttl_every=0.2)

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    # Storing
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    await asleep(0.08)
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.16 second
    await asleep(0.08)
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.24 second
    await asleep(0.08)
    assert await storage.retrieve(key) is None


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_redisstorage_expired(anyio_backend):
    if await is_redis_down():  # pragma: no cover
        pytest.fail("Redis server was not found")
    storage = AsyncRedisStorage(ttl=0.1)
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert await storage.retrieve(first_key) is not None

    await asleep(0.3)
    await storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)

    assert await storage.retrieve(first_key) is None


@pytest.mark.xfail
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_redis_ttl_after_hits(use_temp_dir, anyio_backend):
    storage = AsyncRedisStorage(ttl=0.2)

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    # Storing
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    await asleep(0.08)
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.16 second
    await asleep(0.08)
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.24 second
    await asleep(0.08)
    assert await storage.retrieve(key) is None


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_sqlite_expired(anyio_backend):
    storage = AsyncSQLiteStorage(ttl=0.1, connection=await anysqlite.connect(":memory:"))
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert await storage.retrieve(first_key) is not None

    await asleep(0.3)
    await storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)

    assert await storage.retrieve(first_key) is None


@pytest.mark.xfail
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_sqlite_ttl_after_hits(use_temp_dir, anyio_backend):
    storage = AsyncSQLiteStorage(ttl=0.2)

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    # Storing
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    await asleep(0.08)
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.16 second
    await asleep(0.08)
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.24 second
    await asleep(0.08)
    assert await storage.retrieve(key) is None


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_inmemory_expired(anyio_backend):
    storage = AsyncInMemoryStorage(ttl=0.1)
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    await storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert await storage.retrieve(first_key) is not None

    await asleep(0.3)
    await storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)

    assert await storage.retrieve(first_key) is None


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_inmemory_ttl_after_hits(use_temp_dir, anyio_backend):
    storage = AsyncInMemoryStorage(ttl=0.2)

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    await response.aread()

    # Storing
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    await asleep(0.08)
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.16 second
    await asleep(0.08)
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.24 second
    await asleep(0.08)
    assert await storage.retrieve(key) is None


@pytest.mark.anyio
async def test_filestorage_empty_file_exception(use_temp_dir):
    """When working with concurrency sometimes Hishel
    may leave a cache file empty. In this case this should not
    cause a `JSONDecodeError`, but treat this situation as
    no cache file was created. Issue #180"""

    storage = AsyncFileStorage()
    request = Request(b"GET", "https://example.com")
    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")
    await response.aread()
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    stored_data = await storage.retrieve(key)

    assert stored_data is not None
    filedir = Path(os.getcwd() + "/.cache/hishel/" + key)
    with open(filedir, "w+", encoding="utf-8") as file:
        file.truncate(0)
    assert os.path.getsize(filedir) == 0
    assert await storage.retrieve(key) is None


@pytest.mark.xfail
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_sql_ttl_after_hits(anyio_backend, engine):
    storage = AsyncSQLStorage(
        engine=engine,
        ttl=datetime.timedelta(seconds=0.2),
    )

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    # Storing
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    await asleep(0.08)  # pragma: no cover
    await storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)  # pragma: no cover
    assert await storage.retrieve(key) is not None  # pragma: no cover

    # Retrieving after 0.24 second
    await asleep(0.16)  # pragma: no cover
    assert await storage.retrieve(key) is None  # pragma: no cover


@pytest.mark.xfail
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_sql_expired(anyio_backend, engine):
    storage = AsyncSQLStorage(
        engine=engine,
        ttl=datetime.timedelta(seconds=0.1),
    )
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    await storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert await storage.retrieve(first_key) is not None

    await asleep(0.3)  # pragma: no cover
    await storage.store(
        second_key, response=response, request=second_request, metadata=dummy_metadata
    )  # pragma: no cover

    assert await storage.retrieve(first_key) is None  # pragma: no cover


@pytest.mark.anyio
async def test_filestorage_remove(use_temp_dir):
    storage = AsyncFileStorage()
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    await response.aread()
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None
    await storage.remove(key)
    assert await storage.retrieve(key) is None


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_redisstorage_remove(anyio_backend):
    if await is_redis_down():  # pragma: no cover
        pytest.fail("Redis server was not found")

    storage = AsyncRedisStorage()
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    await response.aread()
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None
    await storage.remove(key)
    assert await storage.retrieve(key) is None


@pytest.mark.anyio
async def test_sqlitestorage_remove():
    storage = AsyncSQLiteStorage(connection=await anysqlite.connect(":memory:"))
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    await response.aread()
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None
    await storage.remove(key)
    assert await storage.retrieve(key) is None


@pytest.mark.anyio
async def test_inmemorystorage_remove():
    storage = AsyncInMemoryStorage()
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    await response.aread()
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None
    await storage.remove(key)
    assert await storage.retrieve(key) is None


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_sql_remove(anyio_backend, engine):
    storage = AsyncSQLStorage(
        engine=engine,
    )
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    await response.aread()
    await storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert await storage.retrieve(key) is not None
    await storage.remove(key)
    assert await storage.retrieve(key) is None
