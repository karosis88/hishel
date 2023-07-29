from httpcore import Request, Response

from hishel._serializers import JSONSerializer, PickleSerializer, YAMLSerializer
from hishel._utils import normalized_url


def test_pickle_serializer_dumps_and_loads():
    request = Request(
        method="GET",
        url="https://example.com",
        headers=[(b"Accept-Encoding", b"gzip")],
        extensions={"sni_hostname": "example.com"},
    )
    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Transfer-Encoding", b"chunked"),
        ],
        content=b"test",
        extensions={"reason_phrase": b"OK", "http_version": b"HTTP/1.1"},
    )
    response.read()
    raw_response = PickleSerializer().dumps(response=response, request=request)

    response, request = PickleSerializer().loads(raw_response)
    response.read()
    assert response.status == 200
    assert response.headers == [
        (b"Content-Type", b"application/json"),
        (b"Transfer-Encoding", b"chunked"),
    ]
    assert response.content == b"test"
    assert response.extensions == {"http_version": b"HTTP/1.1", "reason_phrase": b"OK"}

    assert request.method == b"GET"
    assert normalized_url(request.url) == "https://example.com/"
    assert request.headers == [(b"Accept-Encoding", b"gzip")]
    assert request.extensions == {"sni_hostname": "example.com"}


def test_dict_serializer_dumps():
    request = Request(
        method="GET",
        url="https://example.com",
        headers=[(b"Accept-Encoding", b"gzip")],
        extensions={"sni_hostname": "example.com"},
    )
    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Transfer-Encoding", b"chunked"),
        ],
        content=b"test",
        extensions={"reason_phrase": b"OK", "http_version": b"HTTP/1.1"},
    )
    response.read()
    full_json = JSONSerializer().dumps(response=response, request=request)

    assert full_json == "\n".join(
        [
            "{",
            '    "response": {',
            '        "status": 200,',
            '        "headers": [',
            "            [",
            '                "Content-Type",',
            '                "application/json"',
            "            ],",
            "            [",
            '                "Transfer-Encoding",',
            '                "chunked"',
            "            ]",
            "        ],",
            '        "content": "dGVzdA==",',
            '        "extensions": {',
            '            "reason_phrase": "OK",',
            '            "http_version": "HTTP/1.1"',
            "        }",
            "    },",
            '    "request": {',
            '        "method": "GET",',
            '        "url": "https://example.com/",',
            '        "headers": [',
            "            [",
            '                "Accept-Encoding",',
            '                "gzip"',
            "            ]",
            "        ],",
            '        "extensions": {',
            '            "sni_hostname": "example.com"',
            "        }",
            "    }",
            "}",
        ]
    )


def test_dict_serializer_loads():
    raw_response = "\n".join(
        [
            "{",
            '    "response": {',
            '        "status": 200,',
            '        "headers": [',
            "            [",
            '                "Content-Type",',
            '                "application/json"',
            "            ],",
            "            [",
            '                "Transfer-Encoding",',
            '                "chunked"',
            "            ]",
            "        ],",
            '        "content": "dGVzdA==",',
            '        "extensions": {',
            '            "reason_phrase": "OK",',
            '            "http_version": "HTTP/1.1"',
            "        }",
            "    },",
            '    "request": {',
            '        "method": "GET",',
            '        "url": "https://example.com/",',
            '        "headers": [',
            "            [",
            '                "Accept-Encoding",',
            '                "gzip"',
            "            ]",
            "        ],",
            '        "extensions": {',
            '            "sni_hostname": "example.com"',
            "        }",
            "    }",
            "}",
        ]
    )

    response, request = JSONSerializer().loads(raw_response)
    response.read()
    assert response.status == 200
    assert response.headers == [
        (b"Content-Type", b"application/json"),
        (b"Transfer-Encoding", b"chunked"),
    ]
    assert response.content == b"test"
    assert response.extensions == {"http_version": b"HTTP/1.1", "reason_phrase": b"OK"}

    assert request.method == b"GET"
    assert normalized_url(request.url) == "https://example.com/"
    assert request.headers == [(b"Accept-Encoding", b"gzip")]
    assert request.extensions == {"sni_hostname": "example.com"}


def test_yaml_serializer_dumps():
    request = Request(
        method="GET",
        url="https://example.com",
        headers=[(b"Accept-Encoding", b"gzip")],
        extensions={"sni_hostname": "example.com"},
    )
    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Transfer-Encoding", b"chunked"),
        ],
        content=b"test",
        extensions={"reason_phrase": b"OK", "http_version": b"HTTP/1.1"},
    )
    response.read()
    full_json = YAMLSerializer().dumps(response=response, request=request)

    assert full_json == "\n".join(
        [
            "response:",
            "  status: 200",
            "  headers:",
            "  - - Content-Type",
            "    - application/json",
            "  - - Transfer-Encoding",
            "    - chunked",
            "  content: dGVzdA==",
            "  extensions:",
            "    reason_phrase: OK",
            "    http_version: HTTP/1.1",
            "request:",
            "  method: GET",
            "  url: https://example.com/",
            "  headers:",
            "  - - Accept-Encoding",
            "    - gzip",
            "  extensions:",
            "    sni_hostname: example.com",
            "",
        ]
    )


def test_yaml_serializer_loads():
    raw_response = "\n".join(
        [
            "response:",
            "  status: 200",
            "  headers:",
            "  - - Content-Type",
            "    - application/json",
            "  - - Transfer-Encoding",
            "    - chunked",
            "  content: dGVzdA==",
            "  extensions:",
            "    reason_phrase: OK",
            "    http_version: HTTP/1.1",
            "request:",
            "  method: GET",
            "  url: https://example.com/",
            "  headers:",
            "  - - Accept-Encoding",
            "    - gzip",
            "  extensions:",
            "    sni_hostname: example.com",
            "",
        ]
    )

    response, request = YAMLSerializer().loads(raw_response)
    response.read()
    assert response.status == 200
    assert response.headers == [
        (b"Content-Type", b"application/json"),
        (b"Transfer-Encoding", b"chunked"),
    ]
    assert response.content == b"test"
    assert response.extensions == {"http_version": b"HTTP/1.1", "reason_phrase": b"OK"}

    assert request.method == b"GET"
    assert normalized_url(request.url) == "https://example.com/"
    assert request.headers == [(b"Accept-Encoding", b"gzip")]
    assert request.extensions == {"sni_hostname": "example.com"}
