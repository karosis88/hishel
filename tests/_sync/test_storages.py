import datetime
import os
from pathlib import Path

import sqlite3
import pytest
from httpcore import Request, Response

from hishel import FileStorage, InMemoryStorage, RedisStorage, SQLiteStorage, SQLStorage
from hishel._serializers import Metadata
from hishel._utils import sleep, generate_key

dummy_metadata = Metadata(cache_key="test", number_of_uses=0, created_at=datetime.datetime.now(datetime.timezone.utc))


def is_redis_down() -> bool:
    import redis

    connection = redis.Redis()
    try:
        return not connection.ping()
    except BaseException:  # pragma: no cover
        return True



def test_filestorage(use_temp_dir):
    storage = FileStorage()

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(key, response=response, request=request, metadata=dummy_metadata)

    stored_data = storage.retrieve(key)
    assert stored_data is not None
    stored_response, stored_request, metadata = stored_data
    stored_response.read()
    assert isinstance(stored_response, Response)
    assert stored_response.status == 200
    assert stored_response.headers == []
    assert stored_response.content == b"test"



def test_redisstorage(anyio_backend):
    if is_redis_down():  # pragma: no cover
        pytest.fail("Redis server was not found")
    storage = RedisStorage()

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(key, response=response, request=request, metadata=dummy_metadata)

    stored_data = storage.retrieve(key)
    assert stored_data is not None
    stored_response, stored_request, metadata = stored_data
    stored_response.read()
    assert isinstance(stored_response, Response)
    assert stored_response.status == 200
    assert stored_response.headers == []
    assert stored_response.content == b"test"



def test_sqlitestorage():
    storage = SQLiteStorage(connection=sqlite3.connect(":memory:"))

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(key, response=response, request=request, metadata=dummy_metadata)

    stored_data = storage.retrieve(key)
    assert stored_data is not None
    stored_response, stored_request, metadata = stored_data
    stored_response.read()
    assert isinstance(stored_response, Response)
    assert stored_response.status == 200
    assert stored_response.headers == []
    assert stored_response.content == b"test"



def test_inmemorystorage():
    storage = InMemoryStorage()

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(key, response=response, request=request, metadata=dummy_metadata)

    stored_data = storage.retrieve(key)
    assert stored_data is not None
    stored_response, stored_request, metadata = stored_data
    stored_response.read()
    assert isinstance(stored_response, Response)
    assert stored_response.status == 200
    assert stored_response.headers == []
    assert stored_response.content == b"test"



def test_filestorage_expired(use_temp_dir):
    storage = FileStorage(ttl=0.2, check_ttl_every=0.1)
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert storage.retrieve(first_key) is not None

    sleep(0.3)
    storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)

    assert storage.retrieve(first_key) is None



def test_filestorage_timer(use_temp_dir):
    storage = FileStorage(ttl=0.2, check_ttl_every=0.2)

    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert storage.retrieve(first_key) is not None
    sleep(0.1)
    assert storage.retrieve(first_key) is not None
    storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)
    assert storage.retrieve(second_key) is not None
    sleep(0.1)
    assert storage.retrieve(first_key) is None
    assert storage.retrieve(second_key) is not None
    sleep(0.1)
    assert storage.retrieve(second_key) is None



def test_filestorage_ttl_after_hits(use_temp_dir):
    storage = FileStorage(ttl=0.2, check_ttl_every=0.2)

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    # Storing
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    sleep(0.08)
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.16 second
    sleep(0.08)
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.24 second
    sleep(0.08)
    assert storage.retrieve(key) is None



def test_redisstorage_expired(anyio_backend):
    if is_redis_down():  # pragma: no cover
        pytest.fail("Redis server was not found")
    storage = RedisStorage(ttl=0.1)
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert storage.retrieve(first_key) is not None

    sleep(0.3)
    storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)

    assert storage.retrieve(first_key) is None


@pytest.mark.xfail

def test_redis_ttl_after_hits(use_temp_dir):
    storage = RedisStorage(ttl=0.2)

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    # Storing
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    sleep(0.08)
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.16 second
    sleep(0.08)
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.24 second
    sleep(0.08)
    assert storage.retrieve(key) is None



def test_sqlite_expired(anyio_backend):
    storage = SQLiteStorage(ttl=0.1, connection=sqlite3.connect(":memory:"))
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert storage.retrieve(first_key) is not None

    sleep(0.3)
    storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)

    assert storage.retrieve(first_key) is None


@pytest.mark.xfail

def test_sqlite_ttl_after_hits(use_temp_dir):
    storage = SQLiteStorage(ttl=0.2)

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    # Storing
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    sleep(0.08)
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.16 second
    sleep(0.08)
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.24 second
    sleep(0.08)
    assert storage.retrieve(key) is None



def test_inmemory_expired(anyio_backend):
    storage = InMemoryStorage(ttl=0.1)
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert storage.retrieve(first_key) is not None

    sleep(0.3)
    storage.store(second_key, response=response, request=second_request, metadata=dummy_metadata)

    assert storage.retrieve(first_key) is None



def test_inmemory_ttl_after_hits(use_temp_dir):
    storage = InMemoryStorage(ttl=0.2)

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    # Storing
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    sleep(0.08)
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.16 second
    sleep(0.08)
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.24 second
    sleep(0.08)
    assert storage.retrieve(key) is None



def test_filestorage_empty_file_exception(use_temp_dir):
    """When working with concurrency sometimes Hishel
    may leave a cache file empty. In this case this should not
    cause a `JSONDecodeError`, but treat this situation as
    no cache file was created. Issue #180"""

    storage = FileStorage()
    request = Request(b"GET", "https://example.com")
    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")
    response.read()
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    stored_data = storage.retrieve(key)

    assert stored_data is not None
    filedir = Path(os.getcwd() + "/.cache/hishel/" + key)
    with open(filedir, "w+", encoding="utf-8") as file:
        file.truncate(0)
    assert os.path.getsize(filedir) == 0
    assert storage.retrieve(key) is None


@pytest.mark.xfail

def test_sql_ttl_after_hits(engine):
    storage = SQLStorage(
        engine=engine,
        ttl=datetime.timedelta(seconds=0.2),
    )

    request = Request(b"GET", "https://example.com")

    key = generate_key(request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    # Storing
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None

    # Retrieving after 0.08 second
    sleep(0.08)  # pragma: no cover
    storage.update_metadata(key, response=response, request=request, metadata=dummy_metadata)  # pragma: no cover
    assert storage.retrieve(key) is not None  # pragma: no cover

    # Retrieving after 0.24 second
    sleep(0.16)  # pragma: no cover
    assert storage.retrieve(key) is None  # pragma: no cover


@pytest.mark.xfail

def test_sql_expired(engine):
    storage = SQLStorage(
        engine=engine,
        ttl=datetime.timedelta(seconds=0.1),
    )
    first_request = Request(b"GET", "https://example.com")
    second_request = Request(b"GET", "https://anotherexample.com")

    first_key = generate_key(first_request)
    second_key = generate_key(second_request)

    response = Response(200, headers=[], content=b"test")
    response.read()

    storage.store(first_key, response=response, request=first_request, metadata=dummy_metadata)
    assert storage.retrieve(first_key) is not None

    sleep(0.3)  # pragma: no cover
    storage.store(
        second_key, response=response, request=second_request, metadata=dummy_metadata
    )  # pragma: no cover

    assert storage.retrieve(first_key) is None  # pragma: no cover



def test_filestorage_remove(use_temp_dir):
    storage = FileStorage()
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    response.read()
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None
    storage.remove(key)
    assert storage.retrieve(key) is None



def test_redisstorage_remove(anyio_backend):
    if is_redis_down():  # pragma: no cover
        pytest.fail("Redis server was not found")

    storage = RedisStorage()
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    response.read()
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None
    storage.remove(key)
    assert storage.retrieve(key) is None



def test_sqlitestorage_remove():
    storage = SQLiteStorage(connection=sqlite3.connect(":memory:"))
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    response.read()
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None
    storage.remove(key)
    assert storage.retrieve(key) is None



def test_inmemorystorage_remove():
    storage = InMemoryStorage()
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    response.read()
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None
    storage.remove(key)
    assert storage.retrieve(key) is None



def test_sql_remove(engine):
    storage = SQLStorage(
        engine=engine,
    )
    request = Request(b"GET", "https://example.com")

    key = generate_key(request)
    response = Response(200, headers=[], content=b"test")

    response.read()
    storage.store(key, response=response, request=request, metadata=dummy_metadata)
    assert storage.retrieve(key) is not None
    storage.remove(key)
    assert storage.retrieve(key) is None
