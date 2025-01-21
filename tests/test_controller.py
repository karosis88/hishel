import logging
import re

import pytest
from freezegun import freeze_time
from httpcore import Request, Response

from hishel._controller import (
    Controller,
    allowed_stale,
    get_age,
    get_freshness_lifetime,
    get_heuristic_freshness,
)


def test_is_cachable_for_cachables():
    controller = Controller()

    request = Request(b"GET", b"https://example.com", headers=[])

    response = Response(200, headers=[(b"Expires", b"some-date")])

    assert controller.is_cachable(request=request, response=response)

    response = Response(200, headers=[(b"Cache-Control", b"max-age=10000")])

    assert controller.is_cachable(request=request, response=response)


def test_force_cache_property_for_is_cachable():
    controller = Controller(force_cache=True, cacheable_status_codes=[400])
    request = Request("GET", "https://example.com", extensions={"force_cache": False})
    uncachable_response = Response(status=400)

    assert controller.is_cachable(request=request, response=uncachable_response) is False

    request = Request("GET", "https://example.com")

    assert controller.is_cachable(request=request, response=uncachable_response) is True


@freeze_time("Mon, 25 Aug 2015 12:00:01 GMT")
def test_force_cache_property_for_construct_response_from_cache():
    controller = Controller(force_cache=True)
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com", extensions={"force_cache": False})
    cachable_response = Response(
        200,
        headers=[
            (b"Cache-Control", b"max-age=0"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),  # 1 second before the clock
        ],
    )

    assert isinstance(
        controller.construct_response_from_cache(
            request=request,
            response=cachable_response,
            original_request=original_request,
        ),
        Request,
    )

    request = Request("Get", "https://example.com")

    assert isinstance(
        controller.construct_response_from_cache(
            request=request,
            response=cachable_response,
            original_request=original_request,
        ),
        Response,
    )


def test_is_cachable_for_non_cachables(caplog):
    controller = Controller()

    request = Request(b"GET", b"https://example.com", headers=[])

    response = Response(200, headers=[])

    with caplog.at_level(logging.DEBUG):
        assert not controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as not cachable "
        "since it does not contain any of the required cache directives."
    ]


def test_is_cachable_for_heuristically_cachable(caplog):
    controller = Controller(allow_heuristics=True)

    request = Request(b"GET", b"https://example.com", headers=[])

    response = Response(200, headers=[])

    with caplog.at_level(logging.DEBUG):
        assert controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as "
        "cachable since its status code is heuristically cacheable."
    ]


def test_is_cachable_for_invalid_method(caplog):
    controller = Controller(cacheable_methods=["GET"])

    request = Request(b"POST", b"https://example.com", headers=[])

    response = Response(200, headers=[])

    with caplog.at_level(logging.DEBUG):
        assert not controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        (
            "Considering the resource located at https://example.com/ "
            "as not cachable since the request method (POST) is not in the list of cacheable methods."
        )
    ]


def test_is_cachable_for_post():
    controller = Controller(cacheable_methods=["POST"])

    request = Request(b"POST", b"https://example.com", headers=[])
    response = Response(
        status=200,
        headers=[
            (b"Cache-Control", b"max-age=3600"),
        ],
    )
    assert controller.is_cachable(request=request, response=response)


def test_controller_with_unsupported_method():
    with pytest.raises(
        RuntimeError,
        match=re.escape(
            "Hishel does not support the HTTP method `INVALID_METHOD`.\nPlease use the methods "
            "from this list: ['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT', 'OPTIONS', 'TRACE', 'PATCH']"
        ),
    ):
        Controller(cacheable_methods=["INVALID_METHOD"])


def test_is_cachable_for_unsupported_status(caplog):
    controller = Controller(cacheable_status_codes=[301])

    request = Request(b"GET", b"https://example.com", headers=[])

    response = Response(200, headers=[(b"Expires", b"some-date")])

    with caplog.at_level(logging.DEBUG):
        assert not controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        (
            "Considering the resource located at https://example.com/ "
            "as not cachable since its status code (200) is not in the list of cacheable status codes."
        )
    ]


def test_is_cachable_for_not_final(caplog):
    controller = Controller(cacheable_status_codes=[100])

    request = Request(b"GET", b"https://example.com", headers=[])

    response = Response(100, headers=[(b"Expires", b"some-date")])

    with caplog.at_level(logging.DEBUG):
        assert not controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as "
        "not cachable since its status code is informational."
    ]


def test_is_cachable_for_no_store(caplog):
    controller = Controller(allow_heuristics=True)

    request = Request(b"GET", b"https://example.com", headers=[])

    response = Response(200, headers=[(b"Cache-Control", b"no-store")])

    with caplog.at_level(logging.DEBUG):
        assert not controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as not cachable"
        " since the response contains the no-store directive."
    ]


def test_is_cachable_for_shared_cache():
    controller = Controller(cache_private=False, allow_heuristics=True)

    request = Request(b"GET", b"https://example.com", headers=[])

    response = Response(200, headers=[(b"Cache-Control", b"public")])

    assert controller.is_cachable(request=request, response=response)

    response = Response(200, headers=[(b"Cache-Control", b"private")])

    assert not controller.is_cachable(request=request, response=response)

    response = Response(200, headers=[(b"Cache-Control", b"private=set-cookie")])

    assert not controller.is_cachable(request=request, response=response)


def test_is_cachable_for_private_cache(caplog):
    controller = Controller()

    request = Request(b"GET", b"https://example.com", headers=[])

    response = Response(200, headers=[(b"Cache-Control", b"private")])

    with caplog.at_level(logging.DEBUG):
        assert controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as cachable since it"
        " meets the criteria for being stored in the cache."
    ]


def test_get_freshness_lifetime():
    response = Response(status=200, headers=[(b"Cache-Control", b"max-age=3600")])

    freshness_lifetime = get_freshness_lifetime(response=response)
    assert freshness_lifetime == 3600


def test_get_freshness_omit():
    response = Response(status=200, headers=[])

    freshness_lifetime = get_freshness_lifetime(response=response)
    assert freshness_lifetime is None


def test_get_freshness_lifetime_with_expires():
    response = Response(
        status=200,
        headers=[
            (b"Expires", b"Mon, 25 Aug 2015 12:00:00 GMT"),
            (b"Date", b"Mon, 24 Aug 2015 12:00:00 GMT"),
        ],
    )

    freshness_lifetime = get_freshness_lifetime(response=response)
    assert freshness_lifetime == 86400  # one day


@freeze_time("Mon, Aug 25 2004, 12:00:00 GMT")
def test_get_heuristic_freshness():
    ONE_WEEK = 604_800

    response = Response(status=200, headers=[(b"Last-Modified", "Mon, 25 Aug 2003 12:00:00 GMT")])
    assert get_heuristic_freshness(response=response) == ONE_WEEK


def test_get_heuristic_freshness_without_last_modified():
    ONE_DAY = 86_400

    response = Response(200)
    assert get_heuristic_freshness(response=response) == ONE_DAY


@freeze_time("Tue, 26 Aug 2015 12:00:00 GMT")
def test_get_age():
    response = Response(status=200, headers=[(b"Date", b"Tue, 25 Aug 2015 12:00:00 GMT")])
    age = get_age(response=response)
    assert age == 86400  # One day


def test_get_age_return_inf_for_invalid_date():
    age = get_age(response=Response(status=200))

    assert age == float("inf")


def test_allowed_stale_no_cache():
    response = Response(status=200, headers=[(b"Cache-Control", b"no-cache")])

    assert not allowed_stale(response)


def test_allowed_stale_must_revalidate():
    response = Response(status=200, headers=[(b"Cache-Control", b"must-revalidate")])

    assert not allowed_stale(response)


def test_allowed_stale_allowed():
    response = Response(status=200, headers=[(b"Cache-Control", b"max-age=3600")])

    assert allowed_stale(response)


def test_permanent_redirect_cache(caplog):
    controller = Controller()

    request = Request(b"GET", b"https://example.com")

    response = Response(status=301)

    with caplog.at_level(logging.DEBUG):
        assert controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        (
            "Considering the resource located at https://example.com/ "
            "as cachable since its status code is a permanent redirect."
        )
    ]

    response = Response(status=302)

    assert not controller.is_cachable(request=request, response=response)


def test_make_conditional_request_with_etag(caplog):
    controller = Controller()

    request = Request(
        b"GET",
        b"https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
        ],
    )

    response = Response(status=200, headers=[(b"Etag", b"some-etag")])

    with caplog.at_level(logging.DEBUG):
        controller._make_request_conditional(request=request, response=response)

    assert request.headers == [
        (b"Content-Type", b"application/json"),
        (b"If-None-Match", b"some-etag"),
    ]
    assert caplog.messages == [
        (
            "Adding the 'If-None-Match' header with the value of 'some-etag' "
            "to the request for the resource located at https://example.com/."
        )
    ]


def test_make_conditional_request_with_last_modified(caplog):
    controller = Controller()

    request = Request(
        b"GET",
        b"https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
        ],
    )

    response = Response(status=200, headers=[(b"Last-Modified", b"Wed, 21 Oct 2015 07:28:00 GMT")])

    with caplog.at_level(logging.DEBUG):
        controller._make_request_conditional(request=request, response=response)

    assert request.headers == [
        (b"Content-Type", b"application/json"),
        (b"If-Modified-Since", b"Wed, 21 Oct 2015 07:28:00 GMT"),
    ]
    assert caplog.messages == [
        "Adding the 'If-Modified-Since' header with the value of 'Wed, 21 Oct 2015 07:28:00 GMT' "
        "to the request for the resource located at https://example.com/."
    ]


def test_construct_response_from_cache_redirect(caplog):
    controller = Controller()
    response = Response(status=301)
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")

    with caplog.at_level(logging.DEBUG):
        assert response is controller.construct_response_from_cache(
            request=request, response=response, original_request=original_request
        )

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ "
        "as valid for cache use since its status code is a permanent redirect."
    ]


@freeze_time("Mon, 25 Aug 2003 12:00:00 GMT")
def test_construct_response_from_cache_fresh():
    controller = Controller()
    response = Response(
        status=200,
        headers=[
            (b"Cache-Control", b"max-age=3600"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")
    assert response is controller.construct_response_from_cache(
        request=request, response=response, original_request=original_request
    )


@freeze_time("Mon, 25 Aug 2015 12:00:02 GMT")
def test_construct_response_from_cache_stale():
    controller = Controller()
    response = Response(
        status=200,
        headers=[
            (b"Cache-Control", b"max-age=1"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")
    conditional_request = controller.construct_response_from_cache(
        request=request, response=response, original_request=original_request
    )
    assert isinstance(conditional_request, Request)


def test_construct_response_from_cache_with_always_revalidate(caplog):
    controller = Controller(always_revalidate=True)
    response = Response(
        status=200,
        headers=[
            (b"Cache-Control", b"max-age=1"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")

    with caplog.at_level(logging.DEBUG):
        conditional_request = controller.construct_response_from_cache(
            request=request, response=response, original_request=original_request
        )
        assert isinstance(conditional_request, Request)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ "
        "as needing revalidation since the cache is set to always revalidate."
    ]


def test_construct_response_from_cache_with_must_revalidate(caplog):
    controller = Controller()
    response = Response(
        status=200,
        headers=[
            (b"Cache-Control", b"max-age=1, must-revalidate"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")

    with caplog.at_level(logging.DEBUG):
        conditional_request = controller.construct_response_from_cache(
            request=request, response=response, original_request=original_request
        )
        assert isinstance(conditional_request, Request)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ "
        "as needing revalidation since the response contains the must-revalidate directive."
    ]


def test_construct_response_from_cache_with_request_no_cache(caplog):
    controller = Controller(allow_stale=True)
    response = Response(
        status=200,
        headers=[
            (b"Cache-Control", b"max-age=1"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com", headers=[(b"Cache-Control", b"no-cache")])

    with caplog.at_level(logging.DEBUG):
        conditional_request = controller.construct_response_from_cache(
            request=request, response=response, original_request=original_request
        )
        assert isinstance(conditional_request, Request)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ "
        "as needing revalidation since the request contains the no-cache directive."
    ]


def test_construct_response_from_cache_with_no_cache(caplog):
    controller = Controller(allow_stale=True)
    response = Response(
        status=200,
        headers=[
            (b"Cache-Control", b"max-age=1, no-cache"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")

    with caplog.at_level(logging.DEBUG):
        conditional_request = controller.construct_response_from_cache(
            request=request, response=response, original_request=original_request
        )
        assert isinstance(conditional_request, Request)

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ "
        "as needing revalidation since the response contains the no-cache directive."
    ]


@freeze_time("Mon, 26 Aug 2015 12:00:00 GMT")
def test_construct_response_heuristically(caplog):
    controller = Controller(allow_heuristics=True)

    # Age less than 7 days
    response = Response(
        status=200,
        headers=[
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
            (b"Last-Modified", b"Mon, 25 Aug 2003 12:00:00 GMT"),
        ],
    )
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")

    with caplog.at_level(logging.DEBUG):
        res = controller.construct_response_from_cache(
            request=request, response=response, original_request=original_request
        )
    assert caplog.messages == [
        "Could not determine the freshness lifetime of the resource located at "
        "https://example.com/, trying to use heuristics to calculate it.",
        "Successfully calculated the freshness lifetime of the resource "
        "located at https://example.com/ using heuristics.",
        "Considering the resource located at https://example.com/ as valid for cache use since it is fresh.",
    ]
    assert isinstance(res, Response)

    # Age more than 7 days
    response = Response(
        status=200,
        headers=[
            (b"Date", b"Mon, 18 Aug 2015 12:00:00 GMT"),
            (b"Last-Modified", b"Mon, 25 Aug 2003 12:00:00 GMT"),
        ],
    )

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        res = controller.construct_response_from_cache(
            request=request, response=response, original_request=original_request
        )
    assert caplog.messages == [
        "Could not determine the freshness lifetime of the resource located at "
        "https://example.com/, trying to use heuristics to calculate it.",
        "Successfully calculated the freshness lifetime of the resource"
        " located at https://example.com/ using heuristics.",
        "Considering the resource located at https://example.com/ as needing revalidation since it is not fresh.",
        "Adding the 'If-Modified-Since' header with the value of 'Mon, 25 Aug 2003 12:00:00 GMT'"
        " to the request for the resource located at https://example.com/.",
    ]

    assert not isinstance(res, Response)


def test_handle_validation_response_changed():
    controller = Controller()

    old_response = Response(status=200, headers=[(b"old-response", b"true")], content=b"old")

    new_response = Response(status=200, headers=[(b"new-response", b"true")], content=b"new")

    response = controller.handle_validation_response(old_response=old_response, new_response=new_response)
    response.read()

    assert response.headers == [(b"new-response", b"true")]
    assert response.content == b"new"


def test_handle_validation_response_not_changed():
    controller = Controller()

    old_response = Response(status=200, headers=[(b"old-response", b"true")], content=b"old")

    new_response = Response(
        status=304,
        headers=[(b"new-response", b"false"), (b"old-response", b"true")],
        content=b"new",
    )

    response = controller.handle_validation_response(old_response=old_response, new_response=new_response)
    response.read()

    assert response.headers == [(b"old-response", b"true"), (b"new-response", b"false")]
    assert response.content == b"old"


def test_vary_validation():
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )
    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Vary", b"Content-Type, Content-Language"),
        ],
    )

    controller = Controller()

    assert controller._validate_vary(request=request, response=response, original_request=original_request)

    original_request.headers.pop(0)

    assert not controller._validate_vary(request=request, response=response, original_request=original_request)


def test_construct_response_from_cache_with_vary_mismatch(caplog):
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/xml"),
            (b"Content-Language", b"en-US"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Vary", b"Content-Type, Content-Language"),
        ],
    )

    controller = Controller()

    with caplog.at_level(logging.DEBUG):
        cached_response = controller.construct_response_from_cache(
            original_request=original_request, request=request, response=response
        )

    assert cached_response is None
    assert caplog.messages == [
        "Considering the resource located at https://example.com/ "
        "as invalid for cache use since the vary headers do not match."
    ]


def test_vary_validation_value_mismatch():
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/html"),
            (b"Content-Language", b"en-US"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Vary", b"Content-Type, Content-Language"),
        ],
    )

    controller = Controller()

    assert not controller._validate_vary(request=request, response=response, original_request=original_request)


def test_vary_validation_value_wildcard():
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Vary", b"Content-Type, Content-Language, *"),
        ],
    )

    controller = Controller()

    assert not controller._validate_vary(request=request, response=response, original_request=original_request)


@freeze_time("Mon, 25 Aug 2015 13:00:00 GMT")
def test_max_age_request_directive(caplog):
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", "max-age=3599"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", "max-age=3600"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )

    controller = Controller()

    with caplog.at_level(logging.DEBUG):
        cached_response = controller.construct_response_from_cache(
            original_request=original_request, request=request, response=response
        )
    assert cached_response is None
    assert caplog.messages == [
        (
            "Considering the resource located at https://example.com/ "
            "as invalid for cache use since the age of the response exceeds the max-age directive."
        )
    ]


@freeze_time("Mon, 25 Aug 2015 13:00:00 GMT")
def test_max_age_request_directive_with_max_stale(caplog):
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", "max-age=3600, max-stale=10000"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", "max-age=600"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )

    controller = Controller()

    with caplog.at_level(logging.DEBUG):
        cached_response = controller.construct_response_from_cache(
            original_request=original_request, request=request, response=response
        )

    assert isinstance(cached_response, Response)
    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as valid for "
        "cache use since the freshness lifetime has been exceeded less than max-stale."
    ]


@freeze_time("Mon, 25 Aug 2015 13:00:00 GMT")
def test_max_stale_request_directive(caplog):
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", b"max-stale=2999"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", "max-age=600"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )

    controller = Controller()

    with caplog.at_level(logging.DEBUG):
        cached_response = controller.construct_response_from_cache(
            original_request=original_request, request=request, response=response
        )
    assert cached_response is None
    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as invalid for"
        " cache use since the freshness lifetime has been exceeded more than max-stale."
    ]


@freeze_time("Mon, 25 Aug 2015 13:00:00 GMT")
def test_min_fresh_request_directive(caplog):
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", b"min_fresh=10000"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", "max-age=4000"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )

    controller = Controller()

    with caplog.at_level(logging.DEBUG):
        cached_response = controller.construct_response_from_cache(
            original_request=original_request, request=request, response=response
        )
    assert cached_response is None
    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as invalid for cache"
        " use since the time left for freshness is less than the min-fresh directive."
    ]


def test_no_cache_request_directive():
    original_request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", b"no-cache"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", "max-age=4000"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )

    controller = Controller()

    cached_response = controller.construct_response_from_cache(
        original_request=original_request, request=request, response=response
    )
    assert isinstance(cached_response, Request)


def test_no_store_request_directive():
    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", b"no-store"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", "max-age=4000"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )

    controller = Controller()

    assert not controller.is_cachable(request=request, response=response)


def test_no_store_response_directive():
    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", b"no-store, max-age=4000"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )

    controller = Controller()

    assert not controller.is_cachable(request=request, response=response)


def test_must_understand_response_directive(caplog):
    request = Request(
        method="GET",
        url="https://example.com",
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
        ],
    )

    response = Response(
        status=200,
        headers=[
            (b"Content-Type", b"application/json"),
            (b"Content-Language", b"en-US"),
            (b"Cache-Control", b"no-store, must-understand, max-age=4000"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),
        ],
    )

    controller = Controller()

    with caplog.at_level(logging.DEBUG):
        assert controller.is_cachable(request=request, response=response)

    assert caplog.messages == [
        "Skipping the no-store directive for the resource located at https://example.com/"
        " since the response contains the must-understand directive.",
        "Considering the resource located at https://example.com/ as cachable "
        "since it meets the criteria for being stored in the cache.",
    ]


def test_freshness_lifetime_invalid_information(caplog):
    controller = Controller()
    response = Response(
        status=400,
    )
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")

    with caplog.at_level(logging.DEBUG):
        conditional_request = controller.construct_response_from_cache(
            request=request, response=response, original_request=original_request
        )
    assert isinstance(conditional_request, Request)
    assert caplog.messages == [
        "Could not determine the freshness lifetime of the resource located at https://example.com/, "
        "trying to use heuristics to calculate it.",
        (
            "Could not calculate the freshness lifetime of the resource located at https://example.com/. "
            "Making a conditional request to revalidate the response."
        ),
    ]


def test_force_cache_extension_for_is_cachable(caplog):
    controller = Controller(cacheable_status_codes=[400])
    request = Request("GET", "https://example.com")
    uncachable_response = Response(status=400)

    assert controller.is_cachable(request=request, response=uncachable_response) is False

    request = Request("GET", "https://example.com", extensions={"force_cache": True})

    with caplog.at_level(logging.DEBUG):
        assert controller.is_cachable(request=request, response=uncachable_response) is True

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as"
        " cachable since the request is forced to use the cache."
    ]


@freeze_time("Mon, 25 Aug 2015 12:00:01 GMT")
def test_force_cache_extension_for_construct_response_from_cache(caplog):
    controller = Controller()
    original_request = Request("GET", "https://example.com")
    request = Request("GET", "https://example.com")
    cachable_response = Response(
        200,
        headers=[
            (b"Cache-Control", b"max-age=0"),
            (b"Date", b"Mon, 25 Aug 2015 12:00:00 GMT"),  # 1 second before the clock
        ],
    )

    with caplog.at_level(logging.DEBUG):
        assert isinstance(
            controller.construct_response_from_cache(
                request=request,
                response=cachable_response,
                original_request=original_request,
            ),
            Request,
        )
    assert caplog.messages == [
        "Considering the resource located at https://example.com/ as needing revalidation since it is not fresh."
    ]

    request = Request("Get", "https://example.com", extensions={"force_cache": True})

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        assert isinstance(
            controller.construct_response_from_cache(
                request=request,
                response=cachable_response,
                original_request=original_request,
            ),
            Response,
        )

    assert caplog.messages == [
        "Considering the resource located at https://example.com/ "
        "as valid for cache use since the request is forced to use the cache."
    ]
