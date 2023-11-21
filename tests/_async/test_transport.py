import httpx
import pytest

import hishel
from hishel._utils import BaseClock


@pytest.mark.anyio
async def test_transport_301(use_temp_dir):
    async with hishel.MockAsyncTransport() as transport:
        transport.add_responses([httpx.Response(301, headers=[(b"Location", b"https://example.com")])])
        async with hishel.AsyncCacheTransport(transport=transport) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")

            await cache_transport.handle_async_request(request)
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]


@pytest.mark.anyio
async def test_transport_response_validation(use_temp_dir):
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
    async with hishel.AsyncCacheTransport(transport=transport) as cache_transport:
        request = httpx.Request("GET", "https://www.example.com")

        await cache_transport.handle_async_request(request)
        response = await cache_transport.handle_async_request(request)
        assert response.status_code == 200
        assert response.extensions["from_cache"]
        assert "Content-Type" in response.headers
        assert response.headers["Content-Type"] == "application/json"
        assert await response.aread() == b"test"


@pytest.mark.anyio
async def test_transport_stale_response(use_temp_dir):
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
        async with hishel.AsyncCacheTransport(transport=transport, controller=controller) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            await cache_transport.handle_async_request(request)
            response = await cache_transport.handle_async_request(request)
            assert not response.extensions["from_cache"]


@pytest.mark.anyio
async def test_transport_stale_response_with_connecterror(use_temp_dir):
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
        async with hishel.AsyncCacheTransport(transport=transport, controller=controller) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            await cache_transport.handle_async_request(request)
            response = await cache_transport.handle_async_request(request)
            assert response.extensions["from_cache"]


@pytest.mark.anyio
async def test_transport_with_only_if_cached_directive_without_stored_response(
    use_temp_dir,
):
    controller = hishel.Controller()

    async with hishel.MockAsyncTransport() as transport:
        async with hishel.AsyncCacheTransport(transport=transport, controller=controller) as cache_transport:
            response = await cache_transport.handle_async_request(
                httpx.Request(
                    "GET",
                    "https://www.example.com",
                    headers=[(b"Cache-Control", b"only-if-cached")],
                )
            )
            assert response.status_code == 504


@pytest.mark.anyio
async def test_transport_with_only_if_cached_directive_with_stored_response(
    use_temp_dir,
):
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
        async with hishel.AsyncCacheTransport(transport=transport, controller=controller) as cache_transport:
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
async def test_transport_with_cache_disabled_extension(use_temp_dir):
    class MockedClock(BaseClock):
        def now(self) -> int:
            return 1440504001  # Mon, 25 Aug 2015 12:00:01 GMT

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
            transport=transport, controller=hishel.Controller(clock=MockedClock())
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
