import types
import typing as tp

import httpcore
import httpx
from httpx import Request, Response
from httpx._transports.default import ResponseStream

from hishel._utils import generate_key, normalized_url

from .._controller import Controller
from .._serializers import JSONSerializer
from ._storages import BaseStorage, FileStorage

if tp.TYPE_CHECKING:  # pragma: no cover
    from typing_extensions import Self

__all__ = ("CacheTransport",)


def fake_stream(content: bytes) -> tp.Iterable[bytes]:
    yield content


class CacheTransport(httpx.BaseTransport):
    def __init__(
        self,
        transport: httpx.BaseTransport,
        storage: tp.Optional[BaseStorage] = None,
        controller: tp.Optional[Controller] = None,
    ) -> None:
        self._transport = transport
        self._storage = (
            storage
            if storage is not None
            else FileStorage(serializer=JSONSerializer())
        )
        self._controller = controller if controller is not None else Controller()

    def handle_request(self, request: Request) -> Response:
        httpcore_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        key = generate_key(httpcore_request)
        stored_resposne, stored_request = self._storage.retreive(key)

        if stored_resposne:
            # Try using the stored response if it was discovered.

            res = self._controller.construct_response_from_cache(
                request=httpcore_request, response=stored_resposne
            )

            if isinstance(res, httpcore.Response):
                # Simply use the response if the controller determines it is ready for use.
                assert isinstance(res.stream, tp.Iterable)
                res.extensions["from_cache"] = True  # type: ignore[index]
                return Response(
                    status_code=res.status,
                    headers=res.headers,
                    stream=ResponseStream(res.stream),
                    extensions=res.extensions,
                )

            if isinstance(res, httpcore.Request):
                # Re-validating the response.
                assert isinstance(res.stream, tp.Iterable)
                revalidation_request = Request(
                    method=res.method,
                    url=normalized_url(res.url),
                    headers=res.headers,
                    stream=ResponseStream(res.stream),
                )
                response = self._transport.handle_request(
                    revalidation_request
                )
                assert isinstance(response.stream, tp.Iterable)
                httpcore_response = httpcore.Response(
                    status=response.status_code,
                    headers=response.headers.raw,
                    content=ResponseStream(response.stream),
                    extensions=response.extensions,
                )

                # Merge headers with the stale response.
                full_response = self._controller.handle_validation_response(
                    old_response=stored_resposne, new_response=httpcore_response
                )

                full_response.read()
                self._storage.store(
                    key, response=full_response, request=httpcore_request
                )

                assert isinstance(full_response.stream, tp.Iterable)
                full_response.extensions["from_cache"] = (  # type: ignore[index]
                    httpcore_response.status == 304
                )
                return Response(
                    status_code=full_response.status,
                    headers=full_response.headers,
                    stream=ResponseStream(fake_stream(full_response.content)),
                    extensions=full_response.extensions,
                )

        response = self._transport.handle_request(request)
        assert isinstance(response.stream, tp.Iterable)
        httpcore_response = httpcore.Response(
            status=response.status_code,
            headers=response.headers.raw,
            content=ResponseStream(response.stream),
            extensions=response.extensions,
        )
        httpcore_response.read()

        if self._controller.is_cachable(
            request=httpcore_request, response=httpcore_response
        ):
            self._storage.store(
                key, response=httpcore_response, request=httpcore_request
            )

        response.extensions["from_cache"] = False  # type: ignore[index]
        return Response(
            status_code=httpcore_response.status,
            headers=httpcore_response.headers,
            stream=ResponseStream(fake_stream(httpcore_response.content)),
            extensions=httpcore_response.extensions,
        )

    def close(self) -> None:
        self._storage.close()

    def __enter__(self) -> "Self":
        return self

    def __exit__(
        self,
        exc_type: tp.Optional[tp.Type[BaseException]] = None,
        exc_value: tp.Optional[BaseException] = None,
        traceback: tp.Optional[types.TracebackType] = None,
    ) -> None:
        self.close()
