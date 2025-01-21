from __future__ import annotations

import httpcore
import pytest
import sniffio
from httpcore._models import Request, Response

import hishel
from hishel._utils import BaseClock, extract_header_values, extract_header_values_decoded, header_presents



def test_pool_301():
    with hishel.MockConnectionPool() as pool:
        pool.add_responses([httpcore.Response(301, headers=[(b"Location", b"https://example.com")])])
        with hishel.CacheConnectionPool(pool=pool, storage=hishel.InMemoryStorage()) as cache_pool:
            cache_pool.request("GET", "https://www.example.com")
            response = cache_pool.request("GET", "https://www.example.com")
            assert response.extensions["from_cache"]



def test_pool_response_validation():
    with hishel.MockConnectionPool() as pool:
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
    with hishel.CacheConnectionPool(pool=pool, storage=hishel.InMemoryStorage()) as cache_pool:
        request = httpcore.Request("GET", "https://www.example.com")

        cache_pool.handle_request(request)
        response = cache_pool.handle_request(request)
        assert response.status == 200
        assert response.extensions["from_cache"]
        assert response.extensions["revalidated"]
        assert header_presents(response.headers, b"Content-Type")
        assert extract_header_values(response.headers, b"Content-Type", single=True)[0] == b"application/json"
        assert response.read() == b"test"



def test_pool_stale_response():
    controller = hishel.Controller(allow_stale=True)
    with hishel.MockConnectionPool() as pool:
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
        with hishel.CacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_pool:
            cache_pool.request("GET", "https://www.example.com")
            response = cache_pool.request("GET", "https://www.example.com")
            assert not response.extensions["from_cache"]



def test_pool_stale_response_with_connecterror():
    controller = hishel.Controller(allow_stale=True)

    class ConnectErrorPool(hishel.MockConnectionPool):
        def handle_request(self, request: Request) -> Response:
            if not hasattr(self, "not_first_request"):
                setattr(self, "not_first_request", object())
                return super().handle_request(request)
            raise httpcore._exceptions.ConnectError()

    with ConnectErrorPool() as pool:
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
        with hishel.CacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_pool:
            cache_pool.request("GET", "https://www.example.com")
            response = cache_pool.request("GET", "https://www.example.com")
            assert response.extensions["from_cache"]



def test_pool_with_only_if_cached_directive_without_stored_response():
    controller = hishel.Controller()

    with hishel.MockConnectionPool() as pool:
        with hishel.CacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_pool:
            response = cache_pool.request(
                "GET",
                "https://www.example.com",
                headers=[(b"Cache-Control", b"only-if-cached")],
            )
            assert response.status == 504



def test_pool_with_only_if_cached_directive_with_stored_response():
    controller = hishel.Controller()

    with hishel.MockConnectionPool() as pool:
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
        with hishel.CacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_pool:
            cache_pool.request("GET", "https://www.example.com")
            response = cache_pool.request(
                "GET",
                "https://www.example.com",
                headers=[(b"Cache-Control", b"only-if-cached")],
            )
            assert response.status == 504



def test_pool_with_cache_disabled_extension():
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

    with hishel.MockConnectionPool() as pool:
        pool.add_responses([cachable_response, httpcore.Response(201)])
        with hishel.CacheConnectionPool(
            pool=pool, controller=hishel.Controller(clock=MockedClock()), storage=hishel.InMemoryStorage()
        ) as cache_transport:
            request = httpcore.Request("GET", "https://www.example.com")
            # This should create a cache entry
            cache_transport.handle_request(request)
            # This should return from cache
            response = cache_transport.handle_request(request)
            assert response.extensions["from_cache"]
            # This should ignore the cache
            caching_disabled_request = httpcore.Request(
                "GET", "https://www.example.com", extensions={"cache_disabled": True}
            )
            response = cache_transport.handle_request(caching_disabled_request)
            assert not response.extensions["from_cache"]
            assert response.status == 201



def test_pool_with_custom_key_generator():
    controller = hishel.Controller(key_generator=lambda request, body: request.url.host.decode())

    with hishel.MockConnectionPool() as pool:
        pool.add_responses([httpcore.Response(301)])
        with hishel.CacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_transport:
            request = httpcore.Request("GET", "https://www.example.com")
            # This should create a cache entry
            cache_transport.handle_request(request)
            # This should return from cache
            response = cache_transport.handle_request(request)
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["cache_key"] == "www.example.com"



def test_pool_with_wrong_type_of_storage():
    storage: hishel.FileStorage | hishel.FileStorage

    try:  # pragma: no cover
        sniffio.current_async_library()
        error = "Expected subclass of `Async" "BaseStorage` but got `FileStorage`"
        storage = hishel.FileStorage()
    except sniffio.AsyncLibraryNotFoundError:  # pragma: no cover
        error = "Expected subclass of `BaseStorage` but got `Async" "FileStorage`"
        storage = getattr(hishel, "Async" + "FileStorage")()

    with pytest.raises(TypeError, match=error):
        hishel.CacheConnectionPool(
            pool=hishel.MockConnectionPool(),
            controller=hishel.Controller(),
            storage=storage,  # type: ignore
        )



def test_pool_caching_post_method():
    controller = hishel.Controller(cacheable_methods=["POST"])

    with hishel.MockConnectionPool() as pool:
        pool.add_responses([httpcore.Response(301), httpcore.Response(200)])
        with hishel.CacheConnectionPool(
            pool=pool,
            controller=controller,
            storage=hishel.InMemoryStorage(),
        ) as cache_pool:
            # This should create a cache entry
            cache_pool.request("POST", "https://www.example.com", content=b"request-1")
            # This should return from cache
            response = cache_pool.request("POST", "https://www.example.com", content=b"request-1")
            assert response.extensions["from_cache"]

            # This should create a new cache entry instead of using the previous one
            response = cache_pool.request("POST", "https://www.example.com", content=b"request-2")
            assert response.status == 200
            assert not response.extensions["from_cache"]



def test_revalidation_with_new_content():
    class MockedClock(BaseClock):
        current = 1440504000  # Mon, 25 Aug 2015 12:00:00 GMT

        def now(self) -> int:
            return self.current

    clock = MockedClock()
    controller = hishel.Controller(clock=clock)
    storage = hishel.InMemoryStorage()

    with hishel.MockConnectionPool() as pool:
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
        with hishel.CacheConnectionPool(pool=pool, controller=controller, storage=storage) as cache_pool:
            # Miss, 200, store
            response = cache_pool.handle_request(httpcore.Request("GET", "https://example.com/"))
            assert not response.extensions["from_cache"]

            # Hit
            response = cache_pool.handle_request(httpcore.Request("GET", "https://example.com/"))
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["number_of_uses"] == 1

            # Cache contains the first response content
            stored = storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
            assert stored
            stored_response, stored_request, stored_metadata = stored
            assert extract_header_values_decoded(stored_response.headers, b"Date") == ["Mon, 25 Aug 2015 12:00:00 GMT"]
            assert stored_response.content == b"Hello, World."

            # tic, tac... one second passed
            clock.current += 1  # one second passed

            # Miss (expired), send revalidation, 200, store
            response = cache_pool.handle_request(httpcore.Request("GET", "https://example.com/"))
            assert not response.extensions["from_cache"]

            # Hit (cf issue #239)
            response = cache_pool.handle_request(httpcore.Request("GET", "https://example.com/"))
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["number_of_uses"] == 1

            # Cache was updated and contains the second response content
            stored = storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
            assert stored
            stored_response, stored_request, stored_metadata = stored
            assert extract_header_values_decoded(stored_response.headers, b"Date") == ["Mon, 25 Aug 2015 12:00:01 GMT"]
            assert stored_response.content == b"Eat at Joe's."

            # tic, tac, tic, tac... ten more seconds passed, let's check the 304 behavious is not broken
            clock.current += 10

            # Miss (expired), send revalidation, 304, update metadata but keep previous content
            response = cache_pool.handle_request(httpcore.Request("GET", "https://example.com/"))
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["number_of_uses"] == 2
            stored = storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
            assert stored
            stored_response, stored_request, stored_metadata = stored
            assert extract_header_values_decoded(stored_response.headers, b"Date") == ["Mon, 25 Aug 2015 12:00:11 GMT"]
            assert stored_response.content == b"Eat at Joe's."



def test_poool_revalidation_forward_extensions():
    class MockedClock(BaseClock):
        current = 1440504000  # Mon, 25 Aug 2015 12:00:00 GMT

        def now(self) -> int:
            return self.current

    class MockedConnectionPoolWithExtensionsMemory(hishel.MockConnectionPool):
        def handle_request(self, request: httpcore.Request) -> httpcore.Response:
            self.last_request_extensions = request.extensions
            return super().handle_request(request)

    clock = MockedClock()
    controller = hishel.Controller(clock=clock)

    with MockedConnectionPoolWithExtensionsMemory() as pool:
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
        with hishel.CacheConnectionPool(
            pool=pool, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_pool:
            # first request with extensions
            cache_pool.handle_request(
                httpcore.Request("GET", "https://www.example.com", extensions={"foo": "bar"})
            )
            assert pool.last_request_extensions["foo"] == "bar"

            # cache expires
            clock.current += 1

            # second request with extensions that should be passed to revalidation request
            response = cache_pool.handle_request(
                httpcore.Request("GET", "https://www.example.com", extensions={"foo": "baz"})
            )
            assert response.extensions["revalidated"] is True
            assert pool.last_request_extensions["foo"] == "baz"
