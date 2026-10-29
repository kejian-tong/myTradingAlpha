"""LangGraph SDK stream REST helpers must keep IDs inside one URL path segment."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx
import pytest
from langgraph_sdk._async.http import HttpClient
from langgraph_sdk._async.threads import ThreadsClient
from langgraph_sdk._sync.http import SyncHttpClient
from langgraph_sdk._sync.threads import SyncThreadsClient

ORIGIN = "https://mock.langgraph.invalid:43123"
SYNTHETIC_API_KEY = "synthetic-langgraph-security-test-key"
SYNTHETIC_HEADERS = {"x-api-key": SYNTHETIC_API_KEY}
TERMINAL_STATE = {"values": {"ok": True}, "next": [], "tasks": []}
GRAPH = {"nodes": [], "edges": []}

THREAD_OUTPUT_CASES = (
    pytest.param(
        "thread-123",
        "/threads/thread-123/state",
        "/threads/thread-123/stream/events",
        id="ordinary-control",
    ),
    pytest.param(
        "../assistants/a/graph#",
        "/threads/..%2Fassistants%2Fa%2Fgraph%23/state",
        "/threads/..%2Fassistants%2Fa%2Fgraph%23/stream/events",
        id="traversal-and-fragment",
    ),
    pytest.param(
        "thread?admin=true",
        "/threads/thread%3Fadmin%3Dtrue/state",
        "/threads/thread%3Fadmin%3Dtrue/stream/events",
        id="query-injection",
    ),
    pytest.param(
        "50%/雪",
        "/threads/50%25%2F%E9%9B%AA/state",
        "/threads/50%25%2F%E9%9B%AA/stream/events",
        id="percent-and-unicode",
    ),
)

AGENT_TREE_CASES = (
    pytest.param("assistant-123", "/assistants/assistant-123/graph", id="ordinary-control"),
    pytest.param(
        "../../other/path#",
        "/assistants/..%2F..%2Fother%2Fpath%23/graph",
        id="traversal-and-fragment",
    ),
    pytest.param(
        "agent?admin=/other",
        "/assistants/agent%3Fadmin%3D%2Fother/graph",
        id="query-injection",
    ),
    pytest.param(
        "50%/雪",
        "/assistants/50%25%2F%E9%9B%AA/graph",
        id="percent-and-unicode",
    ),
)


def _strict_mock_handler(
    *, expected_get_path: str, expected_stream_path: str
) -> tuple[
    Callable[[httpx.Request], httpx.Response],
    list[httpx.Request],
    list[httpx.Request],
    list[httpx.Request],
]:
    get_requests: list[httpx.Request] = []
    stream_requests: list[httpx.Request] = []
    seen_requests: list[httpx.Request] = []
    expected_get_raw_path = expected_get_path.encode("ascii")
    expected_stream_raw_path = expected_stream_path.encode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        assert request.url.scheme == "https", "mock SDK request changed scheme"
        assert request.url.host == "mock.langgraph.invalid", "mock SDK request changed host"
        assert request.url.port == 43123, "mock SDK request changed explicit port"
        assert request.headers.get("x-api-key") == SYNTHETIC_API_KEY, (
            "mock SDK request must use only its explicit synthetic API key"
        )
        assert request.url.query == b"", (
            f"mock SDK request gained a query: {request.url.raw_path!r}"
        )
        assert request.url.fragment == "", (
            f"mock SDK request gained a fragment: {request.url.raw_path!r}"
        )

        if request.method == "GET" and request.url.raw_path == expected_get_raw_path:
            get_requests.append(request)
            if expected_get_path.endswith("/state"):
                return httpx.Response(200, json=TERMINAL_STATE)
            if expected_get_path.endswith("/graph"):
                return httpx.Response(200, json=GRAPH)
            raise AssertionError(f"unsupported expected GET route: {expected_get_path}")

        if request.method == "POST" and request.url.raw_path == expected_stream_raw_path:
            stream_requests.append(request)
            assert len(stream_requests) <= 1, "SDK opened more than one lifecycle subscription"
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b"",
            )

        raise AssertionError(
            "unexpected SDK request: "
            f"{request.method} raw_path={request.url.raw_path!r} "
            f"query={request.url.query!r} fragment={request.url.fragment!r}"
        )

    return handler, get_requests, stream_requests, seen_requests


def _assert_request_capture(
    *,
    expected_get_path: str,
    expected_stream_path: str,
    get_requests: list[httpx.Request],
    stream_requests: list[httpx.Request],
    seen_requests: list[httpx.Request],
) -> None:
    assert len(get_requests) == 1, "the intended REST helper GET must happen exactly once"
    assert get_requests[0].url.raw_path == expected_get_path.encode("ascii")
    assert len(stream_requests) <= 1, "lifecycle subscription count exceeded the bound"
    assert all(
        request.url.raw_path == expected_stream_path.encode("ascii")
        for request in stream_requests
    )
    assert len(seen_requests) == len(get_requests) + len(stream_requests)
    for request in seen_requests:
        assert request.url.scheme == "https"
        assert request.url.host == "mock.langgraph.invalid"
        assert request.url.port == 43123
        assert request.url.query == b""
        assert request.url.fragment == ""
        assert request.headers.get("x-api-key") == SYNTHETIC_API_KEY


@pytest.mark.parametrize(
    ("thread_id", "expected_get_path", "expected_stream_path"),
    THREAD_OUTPUT_CASES,
)
def test_sync_thread_output_encodes_thread_id(
    thread_id: str, expected_get_path: str, expected_stream_path: str
) -> None:
    handler, get_requests, stream_requests, seen_requests = _strict_mock_handler(
        expected_get_path=expected_get_path,
        expected_stream_path=expected_stream_path,
    )
    with httpx.Client(transport=httpx.MockTransport(handler), base_url=ORIGIN) as raw_client:
        threads = SyncThreadsClient(SyncHttpClient(raw_client))
        with threads.stream(
            thread_id=thread_id,
            assistant_id="agent-safe",
            headers=SYNTHETIC_HEADERS,
        ) as thread:
            assert thread.output == {"ok": True}

    _assert_request_capture(
        expected_get_path=expected_get_path,
        expected_stream_path=expected_stream_path,
        get_requests=get_requests,
        stream_requests=stream_requests,
        seen_requests=seen_requests,
    )


@pytest.mark.parametrize(("assistant_id", "expected_get_path"), AGENT_TREE_CASES)
def test_sync_agent_get_tree_encodes_assistant_id(
    assistant_id: str, expected_get_path: str
) -> None:
    stream_path = "/threads/thread-for-graph/stream/events"
    handler, get_requests, stream_requests, seen_requests = _strict_mock_handler(
        expected_get_path=expected_get_path,
        expected_stream_path=stream_path,
    )
    with httpx.Client(transport=httpx.MockTransport(handler), base_url=ORIGIN) as raw_client:
        threads = SyncThreadsClient(SyncHttpClient(raw_client))
        with threads.stream(
            thread_id="thread-for-graph",
            assistant_id=assistant_id,
            headers=SYNTHETIC_HEADERS,
        ) as thread:
            assert thread.agent.get_tree() == GRAPH

    _assert_request_capture(
        expected_get_path=expected_get_path,
        expected_stream_path=stream_path,
        get_requests=get_requests,
        stream_requests=stream_requests,
        seen_requests=seen_requests,
    )


@pytest.mark.parametrize(
    ("thread_id", "expected_get_path", "expected_stream_path"),
    THREAD_OUTPUT_CASES,
)
def test_async_thread_output_encodes_thread_id(
    thread_id: str, expected_get_path: str, expected_stream_path: str
) -> None:
    async def run() -> None:
        handler, get_requests, stream_requests, seen_requests = _strict_mock_handler(
            expected_get_path=expected_get_path,
            expected_stream_path=expected_stream_path,
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=ORIGIN,
        ) as raw_client:
            threads = ThreadsClient(HttpClient(raw_client))
            async with threads.stream(
                thread_id=thread_id,
                assistant_id="agent-safe",
                headers=SYNTHETIC_HEADERS,
            ) as thread:
                assert await thread.output == {"ok": True}

        _assert_request_capture(
            expected_get_path=expected_get_path,
            expected_stream_path=expected_stream_path,
            get_requests=get_requests,
            stream_requests=stream_requests,
            seen_requests=seen_requests,
        )

    asyncio.run(run())


@pytest.mark.parametrize(("assistant_id", "expected_get_path"), AGENT_TREE_CASES)
def test_async_agent_get_tree_encodes_assistant_id(
    assistant_id: str, expected_get_path: str
) -> None:
    async def run() -> None:
        stream_path = "/threads/thread-for-graph/stream/events"
        handler, get_requests, stream_requests, seen_requests = _strict_mock_handler(
            expected_get_path=expected_get_path,
            expected_stream_path=stream_path,
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=ORIGIN,
        ) as raw_client:
            threads = ThreadsClient(HttpClient(raw_client))
            async with threads.stream(
                thread_id="thread-for-graph",
                assistant_id=assistant_id,
                headers=SYNTHETIC_HEADERS,
            ) as thread:
                assert await thread.agent.get_tree() == GRAPH

        _assert_request_capture(
            expected_get_path=expected_get_path,
            expected_stream_path=stream_path,
            get_requests=get_requests,
            stream_requests=stream_requests,
            seen_requests=seen_requests,
        )

    asyncio.run(run())
