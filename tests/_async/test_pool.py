import typing as tp

import httpcore
import pytest
import sniffio
from httpcore._models import Request, Response

import hishel
from hishel._utils import BaseClock, extract_header_values, extract_header_values_decoded, header_presents


@pytest.mark.anyio
async def test_pool_301():
    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses([httpcore.Response(301, headers=[(b"Location", b"https://example.com")])])
        async with hishel.AsyncCacheConnectionPool(pool=pool, storage=hishel.AsyncInMemoryStorage()) as cache_pool:
            await cache_pool.request("GET", "https://www.example.com")
            response = await cache_pool.request("GET", "https://www.example.com")
            assert response.extensions["from_cache"]


@pytest.mark.anyio
async def test_pool_response_validation():
    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses(
            [
                httpcore.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                    content=b"test",
                ),
                httpcore.Response(
                    304,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                        (b"Content-Type", b"application/json"),
                    ],
                ),
            ]
        )
    async with hishel.AsyncCacheConnectionPool(pool=pool, storage=hishel.AsyncInMemoryStorage()) as cache_pool:
        request = httpcore.Request("GET", "https://www.example.com")

        await cache_pool.handle_async_request(request)
        response = await cache_pool.handle_async_request(request)
        assert response.status == 200
        assert response.extensions["from_cache"]
        assert response.extensions["revalidated"]
        assert header_presents(response.headers, b"Content-Type")
        assert extract_header_values(response.headers, b"Content-Type", single=True)[0] == b"application/json"
        assert await response.aread() == b"test"


@pytest.mark.anyio
async def test_pool_stale_response():
    controller = hishel.Controller(allow_stale=True)
    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses(
            [
                httpcore.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                ),
                httpcore.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                ),
            ]
        )
        async with hishel.AsyncCacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_pool:
            await cache_pool.request("GET", "https://www.example.com")
            response = await cache_pool.request("GET", "https://www.example.com")
            assert not response.extensions["from_cache"]


@pytest.mark.anyio
async def test_pool_stale_response_with_connecterror():
    controller = hishel.Controller(allow_stale=True)

    class ConnectErrorPool(hishel.MockAsyncConnectionPool):
        async def handle_async_request(self, request: Request) -> Response:
            if not hasattr(self, "not_first_request"):
                setattr(self, "not_first_request", object())
                return await super().handle_async_request(request)
            raise httpcore._exceptions.ConnectError()

    async with ConnectErrorPool() as pool:
        pool.add_responses(
            [
                httpcore.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                ),
            ]
        )
        async with hishel.AsyncCacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_pool:
            await cache_pool.request("GET", "https://www.example.com")
            response = await cache_pool.request("GET", "https://www.example.com")
            assert response.extensions["from_cache"]


@pytest.mark.anyio
async def test_pool_with_only_if_cached_directive_without_stored_response():
    controller = hishel.Controller()

    async with hishel.MockAsyncConnectionPool() as pool:
        async with hishel.AsyncCacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_pool:
            response = await cache_pool.request(
                "GET",
                "https://www.example.com",
                headers=[(b"Cache-Control", b"only-if-cached")],
            )
            assert response.status == 504


@pytest.mark.anyio
async def test_pool_with_only_if_cached_directive_with_stored_response():
    controller = hishel.Controller()

    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses(
            [
                httpcore.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                    content=b"test",
                ),
            ]
        )
        async with hishel.AsyncCacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_pool:
            await cache_pool.request("GET", "https://www.example.com")
            response = await cache_pool.request(
                "GET",
                "https://www.example.com",
                headers=[(b"Cache-Control", b"only-if-cached")],
            )
            assert response.status == 504


@pytest.mark.anyio
async def test_pool_with_cache_disabled_extension():
    class MockedClock(BaseClock):
        def now(self) -> int:
            return 1440504001  # Mon, 25 Aug 2015 12:00:01 GMT

    cachable_response = httpcore.Response(
        200,
        headers=[
            (b"Cache-Control", b"max-age=3600"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),  # 1 second before the clock
        ],
    )

    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses([cachable_response, httpcore.Response(201)])
        async with hishel.AsyncCacheConnectionPool(
            pool=pool, controller=hishel.Controller(clock=MockedClock()), storage=hishel.AsyncInMemoryStorage()
        ) as cache_transport:
            request = httpcore.Request("GET", "https://www.example.com")
            # This should create a cache entry
            await cache_transport.handle_async_request(request)
            # This should return from cache
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]
            # This should ignore the cache
            caching_disabled_request = httpcore.Request(
                "GET", "https://www.example.com", extensions={"cache_disabled": True}
            )
            response = await cache_transport.handle_async_request(caching_disabled_request)
            assert not response.extensions["from_cache"]
            assert response.status == 201


@pytest.mark.anyio
async def test_pool_with_custom_key_generator():
    controller = hishel.Controller(key_generator=lambda request, body: request.url.host.decode())

    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses([httpcore.Response(301)])
        async with hishel.AsyncCacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_transport:
            request = httpcore.Request("GET", "https://www.example.com")
            # This should create a cache entry
            await cache_transport.handle_async_request(request)
            # This should return from cache
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["cache_key"] == "www.example.com"


@pytest.mark.anyio
async def test_pool_with_wrong_type_of_storage():
    storage: tp.Union[hishel.FileStorage, hishel.AsyncFileStorage]

    try:  # pragma: no cover
        sniffio.current_async_library()
        error = "Expected subclass of `Async" "BaseStorage` but got `FileStorage`"
        storage = hishel.FileStorage()
    except sniffio.AsyncLibraryNotFoundError:  # pragma: no cover
        error = "Expected subclass of `BaseStorage` but got `Async" "FileStorage`"
        storage = getattr(hishel, "Async" + "FileStorage")()

    with pytest.raises(TypeError, match=error):
        hishel.AsyncCacheConnectionPool(
            pool=hishel.MockAsyncConnectionPool(),
            controller=hishel.Controller(),
            storage=storage,  # type: ignore
        )


@pytest.mark.anyio
async def test_pool_caching_post_method():
    controller = hishel.Controller(cacheable_methods=["POST"])

    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses([httpcore.Response(301), httpcore.Response(200)])
        async with hishel.AsyncCacheConnectionPool(
            pool=pool,
            controller=controller,
            storage=hishel.AsyncInMemoryStorage(),
        ) as cache_pool:
            # This should create a cache entry
            await cache_pool.request("POST", "https://www.example.com", content=b"request-1")
            # This should return from cache
            response = await cache_pool.request("POST", "https://www.example.com", content=b"request-1")
            assert response.extensions["from_cache"]

            # This should create a new cache entry instead of using the previous one
            response = await cache_pool.request("POST", "https://www.example.com", content=b"request-2")
            assert response.status == 200
            assert not response.extensions["from_cache"]


@pytest.mark.anyio
async def test_pool_revalidation():
    class MockedClock(BaseClock):
        def __init__(self, initial: int):
            self.current = initial

        def now(self) -> int:
            return self.current

        def inc(self, seconds: int = 1) -> None:
            self.current += seconds

    clock = MockedClock(1440504000)  # Tue, 25 Aug 2015 12:00:00 GMT
    controller = hishel.Controller(clock=clock)
    storage = hishel.AsyncInMemoryStorage()

    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses(
            [
                httpcore.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=2"),
                        (b"Date", b"Tue, 25 Aug 2015 12:00:00 GMT"),
                    ],
                    content=b"Hello, World.",
                ),
                httpcore.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=2"),
                        (b"Date", b"Tue, 25 Aug 2015 12:00:02 GMT"),
                    ],
                    content=b"Hello, World.",
                ),
                httpcore.Response(
                    304,
                    headers=[
                        (b"Cache-Control", b"max-age=2"),
                        (b"Date", b"Tue, 25 Aug 2015 12:00:04 GMT"),
                    ],
                ),
            ]
        )
        async with hishel.AsyncCacheConnectionPool(
            pool=pool,
            controller=controller,
            storage=storage,
        ) as cache_pool:
            request = httpcore.Request("GET", "https://example.com/")

            # MISS
            response = await cache_pool.handle_async_request(request)
            assert response.extensions["from_cache"] is False

            # HIT
            clock.inc()
            response = await cache_pool.handle_async_request(request)
            assert response.extensions["from_cache"] is True

            # Cache contains the right date
            stored = await storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
            assert stored
            stored_response, stored_request, stored_metadata = stored
            assert extract_header_values_decoded(stored_response.headers, b"Date") == ["Tue, 25 Aug 2015 12:00:00 GMT"]

            # Found in cache, but expired ... MISS
            clock.inc()
            response = await cache_pool.handle_async_request(request)
            assert response.extensions["from_cache"] is False

            # HIT, new cache version
            clock.inc()
            response = await cache_pool.handle_async_request(request)
            assert response.extensions["from_cache"] is True

            # Cache contains the right date
            stored = await storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
            assert stored
            stored_response, stored_request, stored_metadata = stored
            assert extract_header_values_decoded(stored_response.headers, b"Date") == ["Tue, 25 Aug 2015 12:00:02 GMT"]

            # HIT after revalidation
            clock.inc()
            response = await cache_pool.handle_async_request(request)
            assert response.extensions["from_cache"] is True

            # Date is updated, but the original content is still there (although 304 did not contain it)
            stored = await storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
            assert stored
            stored_response, stored_request, stored_metadata = stored
            assert extract_header_values_decoded(stored_response.headers, b"Date") == ["Tue, 25 Aug 2015 12:00:04 GMT"]
            assert stored_response.status == 200
            stored_response.read()
            assert stored_response.content == b"Hello, World."
