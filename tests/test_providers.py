"""The AI providers (ai/providers.py) and the request wires in ai/client.py: keys and their storage, switching providers,
Sign in with OpenRouter, the chat completions and Claude conversations, errors and short waits, the model lists, and the
routes. Everything runs against mock services; nothing here reaches the network."""
import asyncio
import hashlib
import json
import os
from base64 import urlsafe_b64encode
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from jobportal.ai import client as ai, providers
from jobportal.core import db, settings

SCHEMA = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}


REAL_CLIENT = httpx.AsyncClient  # kept, so a test can swap one mock service for another


def mock_http(monkeypatch, handler) -> None:
    """Route every httpx.AsyncClient request to `handler` instead of the network."""
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def use(provider: str, key: str = "test-key") -> None:
    """Switch to a provider with a saved key, as Settings, AI does."""
    providers.save_key(provider, key)
    providers.set_provider(provider)
    ai.reset_provider_state()


@pytest.fixture
def no_waiting(monkeypatch):
    """Short waits a provider asks for pass at once."""
    waits = []

    async def sleep(seconds):
        waits.append(seconds)
    monkeypatch.setattr(ai.asyncio, "sleep", sleep)
    return waits


# ---------------------------------------------------------------- choosing a provider and keys

def test_chatgpt_is_the_default_and_every_provider_is_listed():
    status = providers.status()
    assert status["provider"] == "chatgpt" and status["ready"] is False and status["keys"] == {}
    assert ai.setup_problem() == "Sign in with ChatGPT first (Settings, AI)."
    ids = [p["id"] for p in providers.listing()]
    assert ids[:2] == ["chatgpt", "openrouter"] and {"openai", "anthropic", "gemini", "custom"} <= set(ids)
    openrouter = next(p for p in providers.listing() if p["id"] == "openrouter")
    assert openrouter["signin"] and openrouter["free"] and openrouter["key_url"].startswith("https://openrouter.ai/")


def test_switching_providers_clears_the_model_choices():
    cfg = settings.get()
    cfg["ai"]["model"] = "gpt-test"
    cfg["ai"]["stages"]["triage"]["model"] = "gpt-mini-test"
    settings.save(cfg)
    providers.set_provider("chatgpt")  # the same provider keeps them
    assert settings.get()["ai"]["model"] == "gpt-test"
    providers.set_provider("gemini")
    ai_cfg = settings.get()["ai"]
    assert ai_cfg["provider"] == "gemini" and ai_cfg["model"] == "" and ai_cfg["stages"]["triage"]["model"] == ""
    with pytest.raises(ValueError):
        providers.set_provider("nowhere")
    with pytest.raises(ValueError, match="http"):
        providers.set_provider("custom", "ftp://example.com")
    providers.set_provider("custom", "https://ai.example.com/v1/")
    assert providers.info()["base"] == "https://ai.example.com/v1"


def test_keys_are_kept_privately_and_never_shown_whole():
    assert providers.problem() == "Sign in with ChatGPT first (Settings, AI)."
    providers.set_provider("anthropic")
    assert providers.problem() == "Add your Claude (Anthropic) key first (Settings, AI)."
    providers.save_key("anthropic", "  sk-ant-test-1234abcd  ")
    assert providers.get_key("anthropic") == "sk-ant-test-1234abcd" and providers.problem() == ""
    status = providers.status()
    assert status["ready"] and status["keys"] == {"anthropic": "ending in abcd"}
    assert "sk-ant-test" not in json.dumps(status)
    if os.name != "nt":
        assert providers.KEYS.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="doesn't look like"):
        providers.save_key("anthropic", "two words")
    with pytest.raises(ValueError, match="doesn't take a key"):
        providers.save_key("chatgpt", "sk-anything")
    providers.forget_key("anthropic")
    assert providers.get_key("anthropic") == "" and not providers.status()["ready"]


def test_another_service_needs_its_address():
    providers.save_key("custom", "local-key-0000")
    providers.set_provider("custom")
    assert providers.problem() == "Give the address of your AI service first (Settings, AI)."
    providers.set_provider("custom", "http://ai.example.com/v1")
    assert providers.problem() == ""


# ---------------------------------------------------------------- Sign in with OpenRouter

def test_sign_in_with_openrouter(monkeypatch):
    url = providers.openrouter_start(8788)
    params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith("https://openrouter.ai/auth?") and params["callback_url"] == "http://127.0.0.1:8788/auth/openrouter"
    assert params["code_challenge_method"] == "S256" and params["key_label"] == "JobPortal"
    verifier = providers._pending[params["state"]]["verifier"]
    expected = urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == expected  # only this process can trade the code
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), body=json.loads(request.content))
        return httpx.Response(200, json={"key": "sk-or-v1-" + "a" * 64, "user_id": "user_1"})
    mock_http(monkeypatch, handler)
    asyncio.run(providers.openrouter_finish({"code": "one-time", "state": params["state"]}))
    assert seen["url"] == providers.OPENROUTER_EXCHANGE
    assert seen["body"] == {"code": "one-time", "code_verifier": verifier, "code_challenge_method": "S256"}
    assert providers.current() == "openrouter" and providers.get_key("openrouter").startswith("sk-or-v1-")
    assert providers.openrouter_key_page().startswith("https://openrouter.ai/keys/")
    with pytest.raises(ValueError, match="old or didn't come from JobPortal"):  # a state can only be used once
        asyncio.run(providers.openrouter_finish({"code": "one-time", "state": params["state"]}))


def test_a_refused_or_broken_openrouter_sign_in(monkeypatch):
    state = parse_qs(urlparse(providers.openrouter_start(8788)).query)["state"][0]
    with pytest.raises(ValueError, match="didn't approve"):
        asyncio.run(providers.openrouter_finish({"state": state}))
    state = parse_qs(urlparse(providers.openrouter_start(8788)).query)["state"][0]
    mock_http(monkeypatch, lambda request: httpx.Response(403, json={"error": "Invalid code or code_verifier"}))
    with pytest.raises(ValueError, match="HTTP 403"):
        asyncio.run(providers.openrouter_finish({"code": "x", "state": state}))
    assert providers.get_key("openrouter") == "" and providers.current() == "chatgpt"


# ---------------------------------------------------------------- the chat completions wire

@pytest.fixture
def chat_mock(monkeypatch):
    """A scripted chat completions service: each request pops the next reply and its body is recorded."""
    state = {"replies": [], "bodies": [], "headers": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "models/gemini-test-flash"}, {"id": "models/text-embedding-9"}]})
        state["bodies"].append(json.loads(request.content))
        state["headers"].append(dict(request.headers))
        reply = state["replies"].pop(0)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

    mock_http(monkeypatch, handler)
    return state


def chat_reply(*calls, content=None, tokens=30, **extra):
    """A chat completions reply with these tool calls ((name, args) or (name, args, extra fields))."""
    tool_calls = [{"id": f"call_{n}", "type": "function", "function": {"name": c[0], "arguments": json.dumps(c[1])}, **(c[2] if len(c) > 2 else {})}
                  for n, c in enumerate(calls)]
    message = {"role": "assistant", "content": content, **({"tool_calls": tool_calls} if tool_calls else {}), **extra}
    return {"choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}], "usage": {"total_tokens": tokens}}


def test_a_chat_provider_conversation(chat_mock, monkeypatch):
    use("gemini")

    async def fake_fetch(url):
        return f"HTTP 200 {url}\n\nJob posting text"
    monkeypatch.setattr(ai, "fetch_public", fake_fetch)
    signature = {"extra_content": {"google": {"thought_signature": "sig-1"}}}
    chat_mock["replies"] = [chat_reply(("fetch_url", {"url": "https://example.com/job"}, signature), tokens=40),
                            chat_reply(("submit_result", {"score": 81}), tokens=60)]
    out = asyncio.run(ai.run("find jobs", system="sys", schema=SCHEMA, stage="hunt", purpose="hunt", web=True))
    assert out["score"] == 81 and out["_tokens"] == 100 and out["_tools"] == {"searches": 0, "pages": 1}
    first, second = chat_mock["bodies"]
    assert chat_mock["headers"][0]["authorization"] == "Bearer test-key"
    assert first["model"] == "gemini-test-flash" and first["tool_choice"] == "auto" and first["reasoning_effort"] == "medium"
    assert first["messages"][0]["role"] == "system" and "submit_result" in first["messages"][0]["content"]
    assert "no search tool" in first["messages"][0]["content"]  # chat providers read pages without hosted search
    assert [t["function"]["name"] for t in first["tools"]] == ["submit_result", "fetch_url"]
    replay, tool_reply = second["messages"][2], second["messages"][3]
    assert replay["tool_calls"][0]["extra_content"] == signature["extra_content"]  # the thought signature goes back unchanged
    assert "content" not in replay
    assert tool_reply == {"role": "tool", "tool_call_id": "call_0", "content": "HTTP 200 https://example.com/job\n\nJob posting text"}


def test_a_plain_text_answer_and_a_model_without_reasoning(chat_mock):
    use("openrouter")
    refused = httpx.Response(400, json={"error": {"code": 400, "message": "Reasoning is not supported for this model"}})
    chat_mock["replies"] = [refused, chat_reply(content="Here you go."), chat_reply(content='{"score": 12}')]
    cfg = settings.get()
    cfg["ai"]["model"] = "vendor/plain-model"
    settings.save(cfg)
    assert asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))["score"] == 12
    bodies = chat_mock["bodies"]
    assert bodies[0]["reasoning"] == {"effort": "low"} and "reasoning" not in bodies[1] and "reasoning" not in bodies[2]
    assert bodies[2]["messages"][-1] == {"role": "user", "content": "Call submit_result now with your final answer."}
    assert chat_mock["headers"][0]["x-title"] == "JobPortal"


def test_mistral_tool_replies_name_their_tool(chat_mock):
    use("mistral")
    cfg = settings.get()
    cfg["ai"]["model"] = "mistral-test"
    settings.save(cfg)
    chat_mock["replies"] = [chat_reply(("send_email", {})), chat_reply(("submit_result", {"score": 4}))]
    assert asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))["score"] == 4
    tool_reply = chat_mock["bodies"][1]["messages"][-1]
    assert tool_reply["name"] == "send_email" and "no tool called send_email" in tool_reply["content"]
    assert "reasoning_effort" not in chat_mock["bodies"][0] and "reasoning" not in chat_mock["bodies"][0]


def test_openrouter_credit_errors_inside_a_200(chat_mock):
    use("openrouter")
    cfg = settings.get()
    cfg["ai"]["model"] = "vendor/paid-model"
    settings.save(cfg)
    chat_mock["replies"] = [{"error": {"code": 402, "message": "Insufficient credits"}}]
    with pytest.raises(ai.UsageLimitError, match="out of credit"):
        asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))
    assert ai.usage_high()


# ---------------------------------------------------------------- the Claude wire

@pytest.fixture
def claude_mock(monkeypatch):
    state = {"replies": [], "bodies": [], "headers": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "claude-opus-test", "max_tokens": 128000},
                                                      {"id": "claude-sonnet-test", "max_tokens": 16000}]})
        state["bodies"].append(json.loads(request.content))
        state["headers"].append(dict(request.headers))
        reply = state["replies"].pop(0)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

    mock_http(monkeypatch, handler)
    use("anthropic", "sk-ant-test-key")
    return state


def claude(*blocks, stop="tool_use", tokens=(20, 10)):
    return {"type": "message", "role": "assistant", "content": list(blocks), "stop_reason": stop,
            "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]}}


def tool_use(name, args, block_id="toolu_1"):
    return {"type": "tool_use", "id": block_id, "name": name, "input": args}


def test_a_claude_conversation_sends_its_blocks_back_unchanged(claude_mock, monkeypatch):
    async def fake_fetch(url):
        return "HTTP 200 page"
    monkeypatch.setattr(ai, "fetch_public", fake_fetch)
    thinking = {"type": "thinking", "thinking": "Let me look.", "signature": "sig-abc"}
    search = {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "nurse jobs Ohio"}}
    results = {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [{"type": "web_search_result",
                                                                                            "url": "https://example.com", "encrypted_content": "enc"}]}
    claude_mock["replies"] = [claude(thinking, search, results, tool_use("fetch_url", {"url": "https://example.com/job"})),
                              claude(tool_use("submit_result", {"score": 90}, "toolu_2"))]
    out = asyncio.run(ai.run("find jobs", system="sys", schema=SCHEMA, stage="hunt", purpose="hunt", web=True))
    assert out["score"] == 90 and out["_tokens"] == 60 and out["_tools"] == {"searches": 1, "pages": 1}
    first, second = claude_mock["bodies"]
    headers = claude_mock["headers"][0]
    assert headers["x-api-key"] == "sk-ant-test-key" and headers["anthropic-version"] == ai.ANTHROPIC_VERSION
    assert first["model"] == "claude-sonnet-test" and first["max_tokens"] == 16000  # the model allows no more
    assert first["tool_choice"] == {"type": "auto"} and first["output_config"] == {"effort": "medium"}
    assert [t.get("name") for t in first["tools"]] == ["submit_result", "fetch_url", "web_search"] and "You can also search" in first["system"]
    assert first["tools"][0]["input_schema"] == SCHEMA
    assert second["messages"][1] == {"role": "assistant", "content": [thinking, search, results,
                                                                      tool_use("fetch_url", {"url": "https://example.com/job"})]}
    assert second["messages"][2] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "HTTP 200 page"}]}


def test_claude_reminders_follow_the_tool_results_and_a_paused_turn_goes_on(claude_mock):
    cfg = settings.get()
    cfg["ai"]["model"] = "claude-opus-test"
    settings.save(cfg)
    claude_mock["replies"] = [claude({"type": "text", "text": "Thinking about it."}, stop="pause_turn"),
                              claude(tool_use("send_email", {})),
                              claude(tool_use("submit_result", {"score": 2}, "toolu_2"))]
    out = asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t", max_steps=1))
    assert out["score"] == 2
    paused, went_on, last = claude_mock["bodies"]
    assert len(went_on["messages"]) == 2 and went_on["messages"][1]["content"] == [{"type": "text", "text": "Thinking about it."}]
    assert last["messages"][1]["content"][-1]["name"] == "send_email"  # the paused turn and its rest are one message
    reply = last["messages"][2]["content"]
    assert reply[0]["type"] == "tool_result" and reply[1]["text"].startswith("You've used your tool budget")


def test_claude_limits_search_refusals_and_effort(claude_mock):
    cfg = settings.get()
    cfg["ai"]["model"] = "claude-opus-test"
    settings.save(cfg)
    too_many = httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
                              "message": "max_tokens: 32000 > 8192, which is the maximum allowed number of output tokens"}})
    no_effort = httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
                               "message": "output_config.effort: not supported for this model"}})
    no_search = httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error",
                               "message": "web search is not enabled for this organization"}})
    claude_mock["replies"] = [too_many, no_effort, no_search, claude(tool_use("submit_result", {"score": 7}))]
    out = asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="hunt", purpose="hunt", web=True))
    assert out["score"] == 7 and ai.web_search_ok is False
    bodies = claude_mock["bodies"]
    assert bodies[1]["max_tokens"] == 8192 and "output_config" not in bodies[2]
    assert any(t.get("name") == "web_search" for t in bodies[2]["tools"]) and not any(t.get("name") == "web_search" for t in bodies[3]["tools"])


# ---------------------------------------------------------------- errors and short waits

@pytest.fixture
def openai_key_mock(monkeypatch):
    state = {"replies": [], "bodies": []}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test-openai"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-6-2026-03-01"}, {"id": "text-embedding-4"}, {"id": "gpt-6-mini"},
                                                      {"id": "gpt-6.1"}, {"id": "whisper-2"}, {"id": "gpt-5.5"}]})
        state["bodies"].append(json.loads(request.content))
        return state["replies"].pop(0)

    mock_http(monkeypatch, handler)
    use("openai", "sk-test-openai")
    return state


def sse(*events) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def streamed(*items, tokens=50):
    events = [{"type": "response.output_item.done", "item": i} for i in items]
    events.append({"type": "response.completed", "response": {"usage": {"total_tokens": tokens}, "output": []}})
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(*events))


def submit(score):
    return {"type": "function_call", "call_id": "c1", "name": "submit_result", "arguments": json.dumps({"score": score})}


def test_the_openai_api_with_a_key(openai_key_mock):
    assert asyncio.run(ai.models()) == ["gpt-6.1", "gpt-5.5", "gpt-6-mini", "gpt-6-2026-03-01"]  # chat models, best first
    no_reasoning = httpx.Response(400, json={"error": {"message": "Unsupported parameter: 'reasoning.effort' is not supported with this model.",
                                                       "type": "invalid_request_error", "param": "reasoning.effort", "code": "unsupported_parameter"}})
    openai_key_mock["replies"] = [no_reasoning, streamed(submit(55))]
    assert asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))["score"] == 55
    first, second = openai_key_mock["bodies"]
    assert first["model"] == "gpt-6.1" and first["reasoning"] == {"effort": "low"} and "reasoning" not in second and "include" not in second
    assert ai.usage()["provider"] == "OpenAI API"


def test_a_short_wait_is_waited_out(openai_key_mock, no_waiting):
    busy = httpx.Response(429, headers={"retry-after": "3"}, json={"error": {"code": "rate_limit_exceeded", "message": "slow down"}})
    openai_key_mock["replies"] = [busy, streamed(submit(8))]
    assert asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))["score"] == 8
    assert no_waiting == [3.0] and not ai.usage_high()


def test_no_credit_and_a_refused_key(openai_key_mock, no_waiting):
    broke = httpx.Response(429, json={"error": {"code": "insufficient_quota", "type": "insufficient_quota", "message": "You exceeded your quota."}})
    openai_key_mock["replies"] = [broke]
    with pytest.raises(ai.UsageLimitError, match="out of credit"):
        asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))
    assert ai.usage_high() and no_waiting == []  # a quota isn't something a moment's wait fixes
    refused = httpx.Response(401, json={"error": {"code": "invalid_api_key", "message": "Incorrect API key provided"}})
    openai_key_mock["replies"] = [refused]
    with pytest.raises(ai.NotSignedIn, match="didn't accept your key"):
        asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))
    assert providers.get_key("openai") == "sk-test-openai"  # kept, so the user can check it


def test_gemini_errors_come_in_a_list():
    err = ai._error_body(json.dumps([{"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "API key not valid. API_KEY_INVALID"}}]))
    assert isinstance(ai._error(err.get("code"), err.get("message"), 400, "gemini"), ai.NotSignedIn)
    quota = ai._error("RESOURCE_EXHAUSTED", "Quota exceeded for metric", 429, "gemini")
    assert isinstance(quota, ai.UsageLimitError) and "Gemini (Google)" in str(quota)
    assert ai._error_body(json.dumps({"error": "Invalid username or password."})) == {"message": "Invalid username or password."}
    spend = ai._error_body(json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": "cap",
                                                                  "details": {"error_code": "enforced_spend_limit_reached"}}}))
    assert spend["code"] == "enforced_spend_limit_reached"


def test_model_lists_per_provider(claude_mock, monkeypatch):
    assert asyncio.run(ai.models()) == ["claude-sonnet-test", "claude-opus-test"]  # Sonnet first, then the rest in Claude's order
    assert ai._model_info["anthropic/claude-opus-test"] == {"max_tokens": 128000}
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"id": "models/gemini-test-flash"},
                                                                              {"id": "models/text-embedding-9"}]}))
    use("gemini")
    assert asyncio.run(ai.models()) == ["gemini-test-flash"]  # "models/" dropped, the embedding model left out


def test_openrouter_lists_only_models_that_call_tools(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/models/user"
        return httpx.Response(200, json={"data": [{"id": "vendor/tools:free", "supported_parameters": ["tools", "reasoning"]},
                                                  {"id": "vendor/chat-only", "supported_parameters": ["temperature"]}]})
    mock_http(monkeypatch, handler)
    use("openrouter")
    assert asyncio.run(ai.models()) == ["vendor/tools:free"]


# ---------------------------------------------------------------- routes

def test_ai_routes(monkeypatch):
    from jobportal.web.server import app
    good = "sk-ant-good-key-9999"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("x-api-key") != good:
            return httpx.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-test"}]})
    mock_http(monkeypatch, handler)
    with TestClient(app) as client:
        listing = client.get("/api/ai/providers").json()
        assert listing["status"]["provider"] == "chatgpt" and len(listing["providers"]) == len(providers.PROVIDERS)
        bad = client.put("/api/ai/key", json={"provider": "anthropic", "key": "sk-ant-wrong-0000"})
        assert bad.status_code == 401 and "didn't accept your key" in bad.json()["detail"]
        assert providers.get_key("anthropic") == "" and providers.current() == "chatgpt"  # nothing kept from a refused key
        ok = client.put("/api/ai/key", json={"provider": "anthropic", "key": good}).json()
        assert ok["ready"] and ok["provider"] == "anthropic" and ok["models"] == ["claude-sonnet-test"]
        assert good not in json.dumps(client.get("/api/ai/status").json())
        assert client.post("/api/ai/provider", json={"provider": "nowhere"}).status_code == 400
        assert client.post("/api/ai/provider", json={"provider": "gemini"}).json()["ready"] is False
        gone = client.delete("/api/ai/key", params={"provider": "anthropic"}).json()
        assert gone["keys"] == {} and gone["key_page"].startswith("https://platform.claude.com/")
        url = client.post("/api/ai/openrouter/signin").json()["url"]
        state = parse_qs(urlparse(url).query)["state"][0]
        page = client.get("/auth/openrouter", params={"state": "forged", "code": "x"})
        assert page.status_code == 200 and "didn" in page.text and providers.get_key("openrouter") == ""
        assert state in providers._pending  # the real sign-in is still waiting
    assert db.one("SELECT COUNT(*) n FROM ai_calls")["n"] == 0  # checking a key isn't an AI task
