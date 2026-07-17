import pytest
from httpx import Headers

from nya.core.streaming import detect_streaming_content, handle_streaming_response
from tests.unit.core_helpers import FakeHttpxResponse


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"content-type": "application/json"}, False),
        ({"content-type": "text/event-stream"}, True),
        ({"transfer-encoding": "chunked", "content-type": "text/plain"}, True),
        (
            {
                "accept-ranges": "bytes",
                "content-type": "video/mp4",
                "content-length": "10",
            },
            True,
        ),
        ({"content-type": "text/plain", "content-length": "10"}, False),
    ],
)
def test_detect_streaming_content(headers, expected):
    assert detect_streaming_content(Headers(headers)) is expected


@pytest.mark.asyncio
async def test_handle_streaming_response_yields_chunks_and_closes_context():
    response = FakeHttpxResponse(
        [b"data: one\n\n", b"", b"data: two\n\n"],
        headers={
            "content-type": "text/event-stream; charset=utf-8",
            "content-length": "100",
            "date": "today",
        },
    )

    streaming = await handle_streaming_response(response)
    body = [chunk async for chunk in streaming.body_iterator]

    assert body == [b"data: one\n\n", b"data: two\n\n"]
    assert response._stream_ctx is None
    assert "content-length" not in streaming.headers
    assert streaming.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_handle_streaming_response_logs_generator_errors_and_closes():
    response = FakeHttpxResponse(
        [],
        headers={"content-type": "text/event-stream"},
        fail=True,
    )

    streaming = await handle_streaming_response(response)
    assert [chunk async for chunk in streaming.body_iterator] == []
    assert response._stream_ctx is None
