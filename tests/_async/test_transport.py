import typing as tp

import httpx
import pytest
import sniffio
from freezegun import freeze_time

import hishel
from hishel._utils import extract_header_values_decoded


@pytest.mark.anyio
async def test_transport_301():
    async with hishel.MockAsyncTransport() as transport:
        transport.add_responses([httpx.Response(301, headers=[(b"Location", b"https://example.com")])])
        async with hishel.AsyncCacheTransport(
            transport=transport, storage=hishel.AsyncInMemoryStorage()
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")

            await cache_transport.handle_async_request(request)
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]


@pytest.mark.anyio
async def test_transport_response_validation():
    async with hishel.MockAsyncTransport() as transport:
        transport.add_responses(
            [
                httpx.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                    content="test",
                ),
                httpx.Response(
                    304,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                        (b"Content-Type", b"application/json"),
                    ],
                ),
            ]
        )
    async with hishel.AsyncCacheTransport(
        transport=transport, storage=hishel.AsyncInMemoryStorage()
    ) as cache_transport:
        request = httpx.Request("GET", "https://www.example.com")

        await cache_transport.handle_async_request(request)
        response = await cache_transport.handle_async_request(request)
        assert response.status_code == 200
        assert response.extensions["from_cache"]
        assert response.extensions["revalidated"]
        assert "Content-Type" in response.headers
        assert response.headers["Content-Type"] == "application/json"
        assert await response.aread() == b"test"


@pytest.mark.anyio
async def test_transport_stale_response():
    controller = hishel.Controller(allow_stale=True)

    async with hishel.MockAsyncTransport() as transport:
        transport.add_responses(
            [
                httpx.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                ),
                httpx.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                ),
            ]
        )
        async with hishel.AsyncCacheTransport(
            transport=transport, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            await cache_transport.handle_async_request(request)
            response = await cache_transport.handle_async_request(request)
            assert not response.extensions["from_cache"]


@pytest.mark.anyio
async def test_transport_stale_response_with_connecterror():
    controller = hishel.Controller(allow_stale=True)

    class ConnectErrorTransport(hishel.MockAsyncTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            if not hasattr(self, "not_first_request"):
                setattr(self, "not_first_request", object())
                return await super().handle_async_request(request)
            raise httpx._exceptions.ConnectError("test")

    async with ConnectErrorTransport() as transport:
        transport.add_responses(
            [
                httpx.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                ),
                httpx.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                ),
            ]
        )
        async with hishel.AsyncCacheTransport(
            transport=transport, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            await cache_transport.handle_async_request(request)
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]


@pytest.mark.anyio
async def test_transport_with_only_if_cached_directive_without_stored_response():
    controller = hishel.Controller()

    async with hishel.MockAsyncTransport() as transport:
        async with hishel.AsyncCacheTransport(
            transport=transport, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_transport:
            response = await cache_transport.handle_async_request(
                httpx.Request(
                    "GET",
                    "https://www.example.com",
                    headers=[(b"Cache-Control", b"only-if-cached")],
                )
            )
            assert response.status_code == 504


@pytest.mark.anyio
async def test_transport_with_only_if_cached_directive_with_stored_response():
    controller = hishel.Controller()

    async with hishel.MockAsyncTransport() as transport:
        transport.add_responses(
            [
                httpx.Response(
                    200,
                    headers=[
                        (b"Cache-Control", b"max-age=3600"),
                        (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                    ],
                    content=b"test",
                ),
            ]
        )
        async with hishel.AsyncCacheTransport(
            transport=transport, controller=controller, storage=hishel.AsyncInMemoryStorage()
        ) as cache_transport:
            await cache_transport.handle_async_request(httpx.Request("GET", "https://www.example.com"))
            response = await cache_transport.handle_async_request(
                httpx.Request(
                    "GET",
                    "https://www.example.com",
                    headers=[(b"Cache-Control", b"only-if-cached")],
                )
            )
            assert response.status_code == 504


@pytest.mark.anyio
@freeze_time("Mon, 25 Aug 2015 12:00:01 GMT")
async def test_transport_with_cache_disabled_extension():
    cachable_response = httpx.Response(
        200,
        headers=[
            (b"Cache-Control", b"max-age=3600"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),  # 1 second before the clock
        ],
    )

    async with hishel.MockAsyncTransport() as transport:
        transport.add_responses([cachable_response, httpx.Response(201)])
        async with hishel.AsyncCacheTransport(
            transport=transport,
            storage=hishel.AsyncInMemoryStorage(),
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            # This should create a cache entry
            await cache_transport.handle_async_request(request)
            # This should return from cache
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]
            # This should ignore the cache
            caching_disabled_request = httpx.Request(
                "GET", "https://www.example.com", extensions={"cache_disabled": True}
            )
            response = await cache_transport.handle_async_request(caching_disabled_request)
            assert not response.extensions["from_cache"]
            assert response.status_code == 201


@pytest.mark.anyio
async def test_transport_with_custom_key_generator():
    controller = hishel.Controller(key_generator=lambda request, body: request.url.host.decode())

    async with hishel.MockAsyncTransport() as transport:
        transport.add_responses([httpx.Response(301)])
        async with hishel.AsyncCacheTransport(
            transport=transport,
            controller=controller,
            storage=hishel.AsyncInMemoryStorage(),
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            # This should create a cache entry
            await cache_transport.handle_async_request(request)
            # This should return from cache
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["cache_key"] == "www.example.com"


@pytest.mark.anyio
async def test_transport_with_wrong_type_of_storage():
    storage: tp.Union[hishel.AsyncFileStorage, hishel.FileStorage]

    try:  # pragma: no cover
        sniffio.current_async_library()
        error = "Expected subclass of `Async" "BaseStorage` but got `FileStorage`"
        storage = hishel.FileStorage()
    except sniffio.AsyncLibraryNotFoundError:  # pragma: no cover
        error = "Expected subclass of `BaseStorage` but got `Async" "FileStorage`"
        storage = getattr(hishel, "Async" + "FileStorage")()

    with pytest.raises(TypeError, match=error):
        hishel.AsyncCacheTransport(
            transport=hishel.MockAsyncTransport(),
            controller=hishel.Controller(),
            storage=storage,  # type: ignore
        )


@pytest.mark.anyio
async def test_transport_caching_post_method():
    controller = hishel.Controller(cacheable_methods=["POST"])

    async with hishel.MockAsyncTransport() as transport:
        transport.add_responses([httpx.Response(301), httpx.Response(200)])
        async with hishel.AsyncCacheTransport(
            transport=transport,
            controller=controller,
            storage=hishel.AsyncInMemoryStorage(),
        ) as cache_transport:
            request = httpx.Request("POST", "https://www.example.com", json={"request": 1})
            # This should create a cache entry
            await cache_transport.handle_async_request(request)
            # This should return from cache
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]

            # Method and URL are the same but the body is different
            request = httpx.Request("POST", "https://www.example.com", json={"request": 2})

            # This should create a new cache entry instead of using the previous one
            response = await cache_transport.handle_async_request(request)
            assert response.status_code == 200
            assert not response.extensions["from_cache"]


@pytest.mark.anyio
async def test_revalidation_with_new_content():
    with freeze_time("Mon, 25 Aug 2015 12:00:00 GMT") as frozen_datetime:
        controller = hishel.Controller()
        storage = hishel.AsyncInMemoryStorage()

        async with hishel.MockAsyncTransport() as transport:
            transport.add_responses(
                [
                    httpx.Response(
                        200,
                        headers=[
                            (b"Cache-Control", b"max-age=1"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                        ],
                        content=b"Hello, World.",
                    ),
                    httpx.Response(
                        200,
                        headers=[
                            (b"Cache-Control", b"max-age=10"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:01 GMT"),
                        ],
                        content=b"Eat at Joe's.",
                    ),
                    httpx.Response(
                        304,
                        headers=[
                            (b"Cache-Control", b"max-age=10"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:11 GMT"),
                        ],
                    ),
                ]
            )
            async with hishel.AsyncCacheTransport(
                transport=transport, controller=controller, storage=storage
            ) as cache_transport:
                # Miss, 200, store
                response = await cache_transport.handle_async_request(httpx.Request("GET", "https://example.com/"))
                assert not response.extensions["from_cache"]

                # Hit
                response = await cache_transport.handle_async_request(httpx.Request("GET", "https://example.com/"))
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
                frozen_datetime.tick()

                # Miss (expired), send revalidation, 200, store
                response = await cache_transport.handle_async_request(httpx.Request("GET", "https://example.com/"))
                assert not response.extensions["from_cache"]

                # Hit (cf issue #239)
                response = await cache_transport.handle_async_request(httpx.Request("GET", "https://example.com/"))
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
                response = await cache_transport.handle_async_request(httpx.Request("GET", "https://example.com/"))
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
async def test_transport_revalidation_forward_extensions():
    class MockedTransportWithExtensionsMemory(hishel.MockAsyncTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.last_request_extensions = request.extensions
            return await super().handle_async_request(request)

    with freeze_time("Mon, 25 Aug 2015 12:00:00 GMT") as frozen_datetime:
        async with MockedTransportWithExtensionsMemory() as transport:
            transport.add_responses(
                [
                    httpx.Response(
                        200,
                        headers=[
                            (b"Cache-Control", b"max-age=1"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
                        ],
                    ),
                    httpx.Response(
                        304,
                        headers=[
                            (b"Cache-Control", b"max-age=1"),
                            (b"Date", b"Mon, 25 Aug 2015 12:00:01 GMT"),
                        ],
                    ),
                ]
            )
            async with hishel.AsyncCacheTransport(
                transport=transport, storage=hishel.AsyncInMemoryStorage()
            ) as cache_transport:
                # first request with extensions
                await cache_transport.handle_async_request(
                    httpx.Request("GET", "https://www.example.com", extensions={"foo": "bar"})
                )
                assert transport.last_request_extensions["foo"] == "bar"

                # cache expires
                frozen_datetime.tick()

                # second request with extensions that should be passed to revalidation request
                response = await cache_transport.handle_async_request(
                    httpx.Request("GET", "https://www.example.com", extensions={"foo": "baz"})
                )
                assert response.extensions["revalidated"] is True
                assert transport.last_request_extensions["foo"] == "baz"
