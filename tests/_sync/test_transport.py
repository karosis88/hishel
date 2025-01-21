from __future__ import annotations

import httpx
import pytest
import sniffio

import hishel
from hishel._utils import BaseClock, extract_header_values_decoded



def test_transport_301():
    with hishel.MockTransport() as transport:
        transport.add_responses([httpx.Response(301, headers=[(b"Location", b"https://example.com")])])
        with hishel.CacheTransport(
            transport=transport, storage=hishel.InMemoryStorage()
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")

            cache_transport.handle_request(request)
            response = cache_transport.handle_request(request)
            assert response.extensions["from_cache"]



def test_transport_response_validation():
    with hishel.MockTransport() as transport:
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
    with hishel.CacheTransport(
        transport=transport, storage=hishel.InMemoryStorage()
    ) as cache_transport:
        request = httpx.Request("GET", "https://www.example.com")

        cache_transport.handle_request(request)
        response = cache_transport.handle_request(request)
        assert response.status_code == 200
        assert response.extensions["from_cache"]
        assert response.extensions["revalidated"]
        assert "Content-Type" in response.headers
        assert response.headers["Content-Type"] == "application/json"
        assert response.read() == b"test"



def test_transport_stale_response():
    controller = hishel.Controller(allow_stale=True)

    with hishel.MockTransport() as transport:
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
        with hishel.CacheTransport(
            transport=transport, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            cache_transport.handle_request(request)
            response = cache_transport.handle_request(request)
            assert not response.extensions["from_cache"]



def test_transport_stale_response_with_connecterror():
    controller = hishel.Controller(allow_stale=True)

    class ConnectErrorTransport(hishel.MockTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            if not hasattr(self, "not_first_request"):
                setattr(self, "not_first_request", object())
                return super().handle_request(request)
            raise httpx._exceptions.ConnectError("test")

    with ConnectErrorTransport() as transport:
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
        with hishel.CacheTransport(
            transport=transport, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            cache_transport.handle_request(request)
            response = cache_transport.handle_request(request)
            assert response.extensions["from_cache"]



def test_transport_with_only_if_cached_directive_without_stored_response():
    controller = hishel.Controller()

    with hishel.MockTransport() as transport:
        with hishel.CacheTransport(
            transport=transport, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_transport:
            response = cache_transport.handle_request(
                httpx.Request(
                    "GET",
                    "https://www.example.com",
                    headers=[(b"Cache-Control", b"only-if-cached")],
                )
            )
            assert response.status_code == 504



def test_transport_with_only_if_cached_directive_with_stored_response():
    controller = hishel.Controller()

    with hishel.MockTransport() as transport:
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
        with hishel.CacheTransport(
            transport=transport, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_transport:
            cache_transport.handle_request(httpx.Request("GET", "https://www.example.com"))
            response = cache_transport.handle_request(
                httpx.Request(
                    "GET",
                    "https://www.example.com",
                    headers=[(b"Cache-Control", b"only-if-cached")],
                )
            )
            assert response.status_code == 504



def test_transport_with_cache_disabled_extension():
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

    with hishel.MockTransport() as transport:
        transport.add_responses([cachable_response, httpx.Response(201)])
        with hishel.CacheTransport(
            transport=transport,
            controller=hishel.Controller(clock=MockedClock()),
            storage=hishel.InMemoryStorage(),
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            # This should create a cache entry
            cache_transport.handle_request(request)
            # This should return from cache
            response = cache_transport.handle_request(request)
            assert response.extensions["from_cache"]
            # This should ignore the cache
            caching_disabled_request = httpx.Request(
                "GET", "https://www.example.com", extensions={"cache_disabled": True}
            )
            response = cache_transport.handle_request(caching_disabled_request)
            assert not response.extensions["from_cache"]
            assert response.status_code == 201



def test_transport_with_custom_key_generator():
    controller = hishel.Controller(key_generator=lambda request, body: request.url.host.decode())

    with hishel.MockTransport() as transport:
        transport.add_responses([httpx.Response(301)])
        with hishel.CacheTransport(
            transport=transport,
            controller=controller,
            storage=hishel.InMemoryStorage(),
        ) as cache_transport:
            request = httpx.Request("GET", "https://www.example.com")
            # This should create a cache entry
            cache_transport.handle_request(request)
            # This should return from cache
            response = cache_transport.handle_request(request)
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["cache_key"] == "www.example.com"



def test_transport_with_wrong_type_of_storage():
    storage: hishel.FileStorage | hishel.FileStorage

    try:  # pragma: no cover
        sniffio.current_async_library()
        error = "Expected subclass of `Async" "BaseStorage` but got `FileStorage`"
        storage = hishel.FileStorage()
    except sniffio.AsyncLibraryNotFoundError:  # pragma: no cover
        error = "Expected subclass of `BaseStorage` but got `Async" "FileStorage`"
        storage = getattr(hishel, "Async" + "FileStorage")()

    with pytest.raises(TypeError, match=error):
        hishel.CacheTransport(
            transport=hishel.MockTransport(),
            controller=hishel.Controller(),
            storage=storage,  # type: ignore
        )



def test_transport_caching_post_method():
    controller = hishel.Controller(cacheable_methods=["POST"])

    with hishel.MockTransport() as transport:
        transport.add_responses([httpx.Response(301), httpx.Response(200)])
        with hishel.CacheTransport(
            transport=transport,
            controller=controller,
            storage=hishel.InMemoryStorage(),
        ) as cache_transport:
            request = httpx.Request("POST", "https://www.example.com", json={"request": 1})
            # This should create a cache entry
            cache_transport.handle_request(request)
            # This should return from cache
            response = cache_transport.handle_request(request)
            assert response.extensions["from_cache"]

            # Method and URL are the same but the body is different
            request = httpx.Request("POST", "https://www.example.com", json={"request": 2})

            # This should create a new cache entry instead of using the previous one
            response = cache_transport.handle_request(request)
            assert response.status_code == 200
            assert not response.extensions["from_cache"]



def test_revalidation_with_new_content():
    class MockedClock(BaseClock):
        current = 1440504000  # Mon, 25 Aug 2015 12:00:00 GMT

        def now(self) -> int:
            return self.current

    clock = MockedClock()
    controller = hishel.Controller(clock=clock)
    storage = hishel.InMemoryStorage()

    with hishel.MockTransport() as transport:
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
        with hishel.CacheTransport(
            transport=transport, controller=controller, storage=storage
        ) as cache_transport:
            # Miss, 200, store
            response = cache_transport.handle_request(httpx.Request("GET", "https://example.com/"))
            assert not response.extensions["from_cache"]

            # Hit
            response = cache_transport.handle_request(httpx.Request("GET", "https://example.com/"))
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["number_of_uses"] == 1

            # Cache contains the first response content
            stored = storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
            assert stored
            stored_response, stored_request, stored_metadata = stored
            assert extract_header_values_decoded(stored_response.headers, b"Date") == ["Mon, 25 Aug 2015 12:00:00 GMT"]
            assert stored_response.content == b"Hello, World."

            # tic, tac... one second passed
            clock.current += 1

            # Miss (expired), send revalidation, 200, store
            response = cache_transport.handle_request(httpx.Request("GET", "https://example.com/"))
            assert not response.extensions["from_cache"]

            # Hit (cf issue #239)
            response = cache_transport.handle_request(httpx.Request("GET", "https://example.com/"))
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
            response = cache_transport.handle_request(httpx.Request("GET", "https://example.com/"))
            assert response.extensions["from_cache"]
            assert response.extensions["cache_metadata"]["number_of_uses"] == 2
            stored = storage.retrieve(response.extensions["cache_metadata"]["cache_key"])
            assert stored
            stored_response, stored_request, stored_metadata = stored
            assert extract_header_values_decoded(stored_response.headers, b"Date") == ["Mon, 25 Aug 2015 12:00:11 GMT"]
            assert stored_response.content == b"Eat at Joe's."



def test_transport_revalidation_forward_extensions():
    class MockedClock(BaseClock):
        current = 1440504000  # Mon, 25 Aug 2015 12:00:00 GMT

        def now(self) -> int:
            return self.current

    class MockedTransportWithExtensionsMemory(hishel.MockTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            self.last_request_extensions = request.extensions
            return super().handle_request(request)

    clock = MockedClock()
    controller = hishel.Controller(clock=clock)

    with MockedTransportWithExtensionsMemory() as transport:
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
        with hishel.CacheTransport(
            transport=transport, controller=controller, storage=hishel.InMemoryStorage()
        ) as cache_transport:
            # first request with extensions
            cache_transport.handle_request(
                httpx.Request("GET", "https://www.example.com", extensions={"foo": "bar"})
            )
            assert transport.last_request_extensions["foo"] == "bar"

            # cache expires
            clock.current += 1

            # second request with extensions that should be passed to revalidation request
            response = cache_transport.handle_request(
                httpx.Request("GET", "https://www.example.com", extensions={"foo": "baz"})
            )
            assert response.extensions["revalidated"] is True
            assert transport.last_request_extensions["foo"] == "baz"
