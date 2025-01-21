import typing as tp

import httpcore
import pytest
import sniffio
from freezegun import freeze_time
from httpcore._models import Request, Response

import hishel
from hishel._utils import extract_header_values, extract_header_values_decoded, header_presents


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
@freeze_time("Mon, 25 Aug 2015 12:00:01 GMT")
async def test_pool_with_cache_disabled_extension():
    cachable_response = httpcore.Response(
        200,
        headers=[
            (b"Cache-Control", b"max-age=3600"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),  # 1 second before the clock
        ],
    )

    async with hishel.MockAsyncConnectionPool() as pool:
        pool.add_responses([cachable_response, httpcore.Response(201)])
        async with hishel.AsyncCacheConnectionPool(pool=pool, storage=hishel.AsyncInMemoryStorage()) as cache_transport:
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
async def test_revalidation_with_new_content():
    with freeze_time("Mon, 25 Aug 2015 12:00:00 GMT") as frozen_datetime:
        storage = hishel.AsyncInMemoryStorage()

        async with hishel.MockAsyncConnectionPool() as pool:
            pool.add_responses(
                [
                    httpcore.Response(
                        200,
                        headers=[
                            (b"Cache-Control", b"max-age=1"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                        ],
                        content=b"Hello, World.",
                    ),
                    httpcore.Response(
                        200,
                        headers=[
                            (b"Cache-Control", b"max-age=10"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:01 GMT"),
                        ],
                        content=b"Eat at Joe's.",
                    ),
                    httpcore.Response(
                        304,
                        headers=[
                            (b"Cache-Control", b"max-age=10"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:11 GMT"),
                        ],
                    ),
                ]
            )
            async with hishel.AsyncCacheConnectionPool(pool=pool, storage=storage) as cache_pool:
                # Miss, 200, store
                response = await cache_pool.handle_async_request(httpcore.Request("GET", "https://example.com/"))
                assert not response.extensions["from_cache"]

                # Hit
                response = await cache_pool.handle_async_request(httpcore.Request("GET", "https://example.com/"))
                assert response.extensions["from_cache"]
                assert response.extensions["cache_metadata"]["number_of_uses"] == 1

                # Cache contains the first response content
                stored = await storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
                assert stored
                stored_response, stored_request, stored_metadata = stored
                assert extract_header_values_decoded(stored_response.headers, b"Date") == [
                    "Mon, 25 Aug 2015 12:00:00 GMT"
                ]
                assert stored_response.content == b"Hello, World."

                # tic, tac... one second passed
                frozen_datetime.tick()  # one second passed

                # Miss (expired), send revalidation, 200, store
                response = await cache_pool.handle_async_request(httpcore.Request("GET", "https://example.com/"))
                assert not response.extensions["from_cache"]

                # Hit (cf issue #239)
                response = await cache_pool.handle_async_request(httpcore.Request("GET", "https://example.com/"))
                assert response.extensions["from_cache"]
                assert response.extensions["cache_metadata"]["number_of_uses"] == 1

                # Cache was updated and contains the second response content
                stored = await storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
                assert stored
                stored_response, stored_request, stored_metadata = stored
                assert extract_header_values_decoded(stored_response.headers, b"Date") == [
                    "Mon, 25 Aug 2015 12:00:01 GMT"
                ]
                assert stored_response.content == b"Eat at Joe's."

                # tic, tac, tic, tac... ten more seconds passed, let's check the 304 behavious is not broken
                frozen_datetime.tick(10)

                # Miss (expired), send revalidation, 304, update metadata but keep previous content
                response = await cache_pool.handle_async_request(httpcore.Request("GET", "https://example.com/"))
                assert response.extensions["from_cache"]
                assert response.extensions["cache_metadata"]["number_of_uses"] == 2
                stored = await storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
                assert stored
                stored_response, stored_request, stored_metadata = stored
                assert extract_header_values_decoded(stored_response.headers, b"Date") == [
                    "Mon, 25 Aug 2015 12:00:11 GMT"
                ]
                assert stored_response.content == b"Eat at Joe's."


@pytest.mark.anyio
async def test_poool_revalidation_forward_extensions():
    class MockedConnectionPoolWithExtensionsMemory(hishel.MockAsyncConnectionPool):
        async def handle_async_request(self, request: httpcore.Request) -> httpcore.Response:
            self.last_request_extensions = request.extensions
            return await super().handle_async_request(request)

    with freeze_time("Mon, 25 Aug 2015 12:00:00 GMT") as frozen_datetime:
        async with MockedConnectionPoolWithExtensionsMemory() as pool:
            pool.add_responses(
                [
                    httpcore.Response(
                        200,
                        headers=[
                            (b"Cache-Control", b"max-age=1"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                        ],
                    ),
                    httpcore.Response(
                        304,
                        headers=[
                            (b"Cache-Control", b"max-age=1"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:01 GMT"),
                        ],
                    ),
                ]
            )
            async with hishel.AsyncCacheConnectionPool(pool=pool, storage=hishel.AsyncInMemoryStorage()) as cache_pool:
                # first request with extensions
                await cache_pool.handle_async_request(
                    httpcore.Request("GET", "https://www.example.com", extensions={"foo": "bar"})
                )
                assert pool.last_request_extensions["foo"] == "bar"

                # cache expires
                frozen_datetime.tick()

                # second request with extensions that should be passed to revalidation request
                response = await cache_pool.handle_async_request(
                    httpcore.Request("GET", "https://www.example.com", extensions={"foo": "baz"})
                )
                assert response.extensions["revalidated"] is True
                assert pool.last_request_extensions["foo"] == "baz"
