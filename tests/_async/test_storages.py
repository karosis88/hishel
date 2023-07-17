import pytest
from httpcore import Request, Response

from hishel import AsyncFileStorage
from hishel._utils import generate_key


@pytest.mark.anyio
async def test_filestorage(use_temp_dir):

    storage = AsyncFileStorage()

    request = Request(
        b"GET",
        "https://example.com"
    )

    key = generate_key(
        request.method,
        request.url,
        request.headers
    )

    response = Response(
        200,
        headers=[],
        content=b'test'
    )

    await storage.store(key, response)

    storead_response = await storage.retreive(key)
    assert storead_response is not None
    storead_response.read()
    assert isinstance(storead_response, Response)
    assert storead_response.status == 200
    assert storead_response.headers == []
    assert storead_response.content == b'test'

@pytest.mark.anyio
async def test_filestorage_delete(use_temp_dir):

    storage = AsyncFileStorage()

    request = Request(
        b"GET",
        "https://example.com"
    )

    key = generate_key(
        request.method,
        request.url,
        request.headers
    )

    response = Response(
        200,
        headers=[],
        content=b'test'
    )

    await storage.store(key, response)

    stored_response = await storage.retreive(key)
    assert stored_response

    await storage.delete(key)
    assert not await storage.retreive(key)
