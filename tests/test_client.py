import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import ClientSession, web

from custom_components.antigravity import const
from custom_components.antigravity.api.client import (
    AntigravityClient,
    Finish,
    InlineData,
    TextDelta,
    ThoughtDelta,
    ToolCall,
    Usage,
)
from custom_components.antigravity.api.errors import (
    AuthError,
    NativeToolRefusedError,
    QuotaExhaustedError,
    RateLimitError,
    UnknownModelError,
    UpstreamError,
)
from custom_components.antigravity.api.search import web_search
from custom_components.antigravity.api.turn import ToolSpec, build_tools


def sse(*chunks) -> str:
    return "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in chunks)


def chunk(*parts, finish=None, usage=None, grounding=None):
    candidate = {"content": {"role": "model", "parts": list(parts)}}
    if finish:
        candidate["finishReason"] = finish
    if grounding:
        candidate["groundingMetadata"] = grounding
    response = {"candidates": [candidate]}
    if usage:
        response["usageMetadata"] = usage
    return {"response": response, "traceId": "t"}


def rpc_error(status, reason=None, message="err"):
    details = (
        [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": reason,
                "domain": "cloudcode-pa.googleapis.com",
            }
        ]
        if reason
        else []
    )
    return {"error": {"code": status, "status": "RESOURCE_EXHAUSTED", "message": message, "details": details}}


STREAM = "streamGenerateContent"
MODELS = "fetchAvailableModels"
QUOTA = "retrieveUserQuotaSummary"


class FakeUpstream:
    """Local stand-in for `v1internal`: queued replies per RPC, recorded requests."""

    def __init__(self) -> None:
        self.replies: dict[str, list[web.Response]] = {}
        self.requests: dict[str, list[tuple[dict, dict]]] = {}

    def post(self, rpc, *, status=200, payload=None, body=None, repeat=1):
        for _ in range(repeat):
            if body is not None:
                reply = web.Response(status=status, text=body)
            else:
                reply = web.json_response(payload, status=status)
            self.replies.setdefault(rpc, []).append(reply)

    async def handle(self, request: web.Request) -> web.Response:
        rpc = request.match_info["rpc"]
        self.requests.setdefault(rpc, []).append((await request.json(), dict(request.headers)))
        return self.replies[rpc].pop(0)


@pytest.fixture
async def mocked(aiohttp_server):
    fake = FakeUpstream()
    app = web.Application()
    app.router.add_post("/v1internal:{rpc}", fake.handle)
    fake.server = await aiohttp_server(app)
    return fake


@pytest.fixture
def tokens():
    return AsyncMock(side_effect=lambda force: "fresh" if force else "tok")


@pytest.fixture
async def client(mocked, tokens):
    async with ClientSession() as session:
        yield AntigravityClient(session, tokens, "proj-1", str(mocked.server.make_url("/v1internal")))


async def collect(client, **kwargs):
    return [e async for e in client.stream_generate("gemini-3.8-flash-low", {"contents": []}, **kwargs)]


async def test_stream_events_and_envelope(client, mocked):
    mocked.post(
        STREAM,
        body=sse(
            chunk({"text": "hmm", "thought": True}, usage={"promptTokenCount": 3, "thoughtsTokenCount": 9}),
            chunk({"text": "Hello"}),
            chunk({"text": " world"}, {"inlineData": {"mimeType": "image/png", "data": "aGk="}}),
            chunk(
                {"text": "", "thoughtSignature": "s"},
                finish="STOP",
                usage={"promptTokenCount": 3, "candidatesTokenCount": 2, "thoughtsTokenCount": 9},
            ),
        ),
    )
    events = await collect(client)
    assert events == [
        ThoughtDelta("hmm"),
        TextDelta("Hello"),
        TextDelta(" world"),
        InlineData("image/png", b"hi"),
        Usage(3, 2, 9, 0),
        Finish("STOP", None),
    ]
    body, headers = mocked.requests[STREAM][0]
    assert body["project"] == "proj-1"
    assert body["model"] == "gemini-3.8-flash-low"
    assert body["requestType"] == "agent"
    assert body["userAgent"] == "antigravity"
    assert headers["Authorization"] == "Bearer tok"
    assert headers["User-Agent"].startswith(f"antigravity/cli/{const.CLI_VERSION} ")


async def test_tool_call_mapped_back(client, mocked):
    _, mapper = build_tools([ToolSpec("light.turn-on", None, {})])
    mocked.post(
        STREAM,
        body=sse(
            chunk(
                {
                    "functionCall": {"name": "light_turn_on", "args": {"entity": "x"}, "id": "c9"},
                    "thoughtSignature": "sig",
                },
                finish="STOP",
            )
        ),
    )
    events = await collect(client, tool_names=mapper)
    assert events[0] == ToolCall("c9", "light.turn-on", {"entity": "x"}, "sig")


@pytest.mark.parametrize("offered", [None, ["other"]])
async def test_unoffered_tool_refused(client, mocked, offered):
    mapper = build_tools([ToolSpec(n, None, {}) for n in offered])[1] if offered else None
    mocked.post(STREAM, body=sse(chunk({"functionCall": {"name": "run_command", "args": {}}}, finish="STOP")))
    with pytest.raises(NativeToolRefusedError, match="native tool refused: run_command"):
        await collect(client, tool_names=mapper)


async def test_native_tools_offered(client, mocked):
    mocked.post(STREAM, body=sse({"response": {"native_tools": ["run_command"]}}))
    with pytest.raises(UpstreamError, match="native tools offered"):
        await collect(client)


async def test_stream_without_finish_fails(client, mocked):
    mocked.post(STREAM, body=sse(chunk({"text": "partial"})))
    with pytest.raises(UpstreamError, match="without a finish"):
        await collect(client)


async def test_error_chunk(client, mocked):
    mocked.post(STREAM, body=sse({"error": {"status": "INTERNAL", "message": "boom"}}))
    with pytest.raises(UpstreamError, match="INTERNAL: boom"):
        await collect(client)


async def test_401_refreshes_once_and_retries(client, mocked, tokens):
    mocked.post(STREAM, status=401, payload={"error": {"status": "UNAUTHENTICATED", "message": "x"}})
    mocked.post(STREAM, body=sse(chunk({"text": "ok"}, finish="STOP")))
    assert (await collect(client))[0] == TextDelta("ok")
    assert [c.args for c in tokens.await_args_list] == [(False,), (True,), (False,)]


async def test_second_401_is_auth_error(client, mocked):
    mocked.post(STREAM, status=401, payload={}, repeat=2)
    with pytest.raises(AuthError):
        await collect(client)


async def test_permission_denied_403_is_auth_error_without_refresh(client, mocked, tokens):
    mocked.post(STREAM, status=403, payload={"error": {"status": "PERMISSION_DENIED", "message": "no"}})
    with pytest.raises(AuthError, match="PERMISSION_DENIED"):
        await collect(client)
    assert tokens.await_count == 1


async def test_transient_429_retried_then_succeeds(client, mocked):
    mocked.post(STREAM, status=429, payload=rpc_error(429, "MODEL_CAPACITY_EXHAUSTED"))
    mocked.post(STREAM, body=sse(chunk({"text": "ok"}, finish="STOP")))
    with patch("custom_components.antigravity.api.client.asyncio.sleep", new=AsyncMock()) as sleep:
        assert (await collect(client))[0] == TextDelta("ok")
    sleep.assert_awaited_once_with(1.0)


async def test_transient_429_gives_up_after_two_retries(client, mocked):
    mocked.post(STREAM, status=429, payload=rpc_error(429, "RATE_LIMIT_EXCEEDED"), repeat=3)
    with (
        patch("custom_components.antigravity.api.client.asyncio.sleep", new=AsyncMock()) as sleep,
        pytest.raises(RateLimitError),
    ):
        await collect(client)
    assert sleep.await_count == 2


async def test_terminal_quota(client, mocked):
    body = rpc_error(429, "QUOTA_EXHAUSTED", "Resets in 1h")
    body["error"]["details"][0]["metadata"] = {"quotaResetTimeStamp": "2026-11-10T01:00:00Z"}
    mocked.post(STREAM, status=429, payload=body)
    with pytest.raises(QuotaExhaustedError) as err:
        await collect(client)
    assert err.value.reset_at == datetime(2026, 11, 10, 1, tzinfo=UTC)


async def test_404_unknown_model(client, mocked):
    mocked.post(STREAM, status=404, payload={"error": {"status": "NOT_FOUND", "message": "nope"}})
    with pytest.raises(UnknownModelError, match="NOT_FOUND"):
        await collect(client)


async def test_fetch_catalog_and_quota(client, mocked, models_payload, quota_payload):
    mocked.post(MODELS, payload=models_payload)
    mocked.post(QUOTA, payload=quota_payload)
    assert (await client.fetch_catalog()).default_model == "gemini-4-argon"
    assert len(await client.fetch_quota()) == 5
    assert mocked.requests[MODELS][0][0] == {"project": "proj-1"}


async def test_web_search(client, mocked):
    grounding = {
        "webSearchQueries": ["f1 winner"],
        "groundingChunks": [
            {"web": {"uri": "https://a", "title": "A"}},
            {"web": {"uri": "https://a", "title": "A"}},
            {"web": {"uri": "https://b"}},
        ],
    }
    mocked.post(STREAM, body=sse(chunk({"text": "Max won."}), chunk({"text": ""}, finish="STOP", grounding=grounding)))
    result = await web_search(client, " who won? ", freshness="week")
    assert result.answer == "Max won."
    assert [(s.title, s.url) for s in result.sources] == [("A", "https://a"), ("https://b", "https://b")]
    assert result.queries == ("f1 winner",)
    body = mocked.requests[STREAM][0][0]
    assert body["request"]["tools"] == [{"googleSearch": {}}]
    assert body["request"]["contents"][0]["parts"][0]["text"].startswith("who won?\n\nSearch recency")
