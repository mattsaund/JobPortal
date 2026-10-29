"""Sign in with ChatGPT and the Responses API loop, against a mock OpenAI. Nothing here reaches the network."""
import asyncio
import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from jobportal.ai import client as ai, signin
from jobportal.core import bus, db


def jwt(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


def query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def mock_http(monkeypatch, handler) -> None:
    """Route every httpx.AsyncClient request to `handler` instead of the network."""
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def sign_in(monkeypatch, email="jordan.rivera@example.com") -> dict:
    """Run the whole redirect flow with a fake token endpoint; returns the authorize parameters that were used."""
    params = query(signin.start(8788))

    async def token(form):
        assert form["grant_type"] == "authorization_code" and form["code_verifier"] and form["resource"] == signin.RESOURCE
        return {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 3600, "scope": signin.SCOPES,
                "id_token": jwt({"iss": signin.ISSUER, "aud": "oaiapp_test", "nonce": params["nonce"], "exp": time.time() + 600,
                                 "sub": "user-1", "email": email, "name": "Jordan"})}
    monkeypatch.setattr(signin, "_token_request", token)
    asyncio.run(signin.finish({"code": "abc", "state": params["state"], "client_id": "oaiapp_test"}))
    return params


def test_first_authorize_url_registers_the_app():
    p = query(signin.start(8788))
    assert p["client_id"] == "dynamic_agent_client" and p["agent_name_hint"] == "JobPortal"
    assert p["ext_agent_host_id"].startswith("urn:uuid:")
    assert p["redirect_uri"] == "http://127.0.0.1:8788/auth/callback"
    assert "chatgpt.tokens.use.direct" in p["scope"].split() and p["resource"] == "https://api.openai.com/v1"
    assert p["code_challenge_method"] == "S256" and p["state"] in signin._pending


def test_sign_in_flow_and_reauthorization(monkeypatch):
    first = sign_in(monkeypatch)
    st = signin.status()
    assert st["signed_in"] and st["email"] == "jordan.rivera@example.com"
    again = query(signin.start(9000))
    assert again["client_id"] == "oaiapp_test" and "agent_name_hint" not in again
    assert again["ext_agent_host_id"] == first["ext_agent_host_id"] and again["login_hint"] == "jordan.rivera@example.com"
    assert "access-1" not in json.dumps(st)  # tokens never leave the server


def test_sign_in_rejects_a_bad_state_or_nonce(monkeypatch):
    with pytest.raises(signin.AuthError, match="expired"):
        asyncio.run(signin.finish({"code": "x", "state": "nope", "client_id": "oaiapp_test"}))
    params = query(signin.start(8788))

    async def token(form):
        return {"access_token": "a", "refresh_token": "r", "scope": signin.SCOPES,
                "id_token": jwt({"iss": signin.ISSUER, "aud": "oaiapp_test", "nonce": "wrong", "exp": time.time() + 600})}
    monkeypatch.setattr(signin, "_token_request", token)
    with pytest.raises(signin.AuthError, match="didn't check out"):
        asyncio.run(signin.finish({"code": "abc", "state": params["state"], "client_id": "oaiapp_test"}))
    assert not signin.status()["signed_in"]


def test_a_stale_sign_in_link_is_refused():
    params = query(signin.start(8788))
    signin._pending[params["state"]]["created"] -= signin.SIGN_IN_TIMEOUT + 1
    with pytest.raises(signin.AuthError, match="expired"):
        asyncio.run(signin.finish({"code": "abc", "state": params["state"], "client_id": "oaiapp_test"}))


def test_refresh_rotates_tokens(monkeypatch):
    sign_in(monkeypatch)
    d = signin._load()
    d["expires_at"] = time.time() - 1
    signin._save(d)

    async def refresh(form):
        assert form["grant_type"] == "refresh_token" and form["refresh_token"] == "refresh-1" and form["client_id"] == "oaiapp_test"
        assert "scope" not in form
        return {"access_token": "access-2", "refresh_token": "refresh-2", "expires_in": 3600}
    monkeypatch.setattr(signin, "_token_request", refresh)
    assert asyncio.run(signin.access_token()) == "access-2"
    assert signin._load()["refresh_token"] == "refresh-2"


@pytest.mark.parametrize("reply, ends_sign_in", [
    ({"error": "invalid_grant", "error_description": "Refresh token expired"}, True),
    ({"error": {"code": "invalid_grant", "message": "Refresh token expired"}}, True),
    ({"error": "temporarily_unavailable"}, False),
])
def test_a_refused_refresh(monkeypatch, reply, ends_sign_in):
    real_token_request = signin._token_request
    sign_in(monkeypatch)
    monkeypatch.setattr(signin, "_token_request", real_token_request)
    d = signin._load()
    d["expires_at"] = time.time() - 1
    signin._save(d)

    def token_endpoint(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == signin.TOKEN_URL
        return httpx.Response(400, json=reply)
    mock_http(monkeypatch, token_endpoint)
    with pytest.raises(signin.AuthError) as raised:
        asyncio.run(signin.access_token())
    assert isinstance(raised.value, signin.NotSignedIn) == ends_sign_in
    assert signin.status()["signed_in"] != ends_sign_in  # only invalid_grant ends the sign-in
    assert signin._load()["client_id"] == "oaiapp_test"  # the registration is kept for the next sign-in


def test_sign_out_forgets_the_tokens_even_when_offline(monkeypatch):
    sign_in(monkeypatch)

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)
    mock_http(monkeypatch, offline)
    out = asyncio.run(signin.sign_out())
    assert not out["signed_in"] and "Couldn't reach OpenAI" in out["note"]
    assert "refresh_token" not in signin._load()


def test_not_signed_in_is_a_clear_error():
    with pytest.raises(ai.NotSignedIn, match="Sign in with ChatGPT"):
        asyncio.run(ai.run("hi", system="s", schema={"type": "object"}, stage="triage", purpose="t"))


# ---------------------------------------------------------------- the Responses loop

def sse(*events) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def done(tokens=50):
    return {"type": "response.completed", "response": {"usage": {"total_tokens": tokens}, "output": []}}


def item(i):
    return {"type": "response.output_item.done", "item": i}


@pytest.fixture
def openai_mock(monkeypatch):
    """A scripted OpenAI: each /responses call pops the next reply. Records every request body."""
    state = {"replies": [], "bodies": []}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-test", "visibility": "list"}, {"id": "hidden", "visibility": "hide"}]})
        state["bodies"].append(json.loads(request.content))
        reply = state["replies"].pop(0)
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse(*reply))

    mock_http(monkeypatch, handler)

    async def token():
        return "test-token"
    monkeypatch.setattr(signin, "access_token", token)
    return state


SCHEMA = {"type": "object", "properties": {"score": {"type": "integer"}}, "required": ["score"]}


def call(name, args, call_id="c1"):
    return item({"type": "function_call", "id": "fc_1", "call_id": call_id, "name": name, "arguments": json.dumps(args), "namespace": "jobportal"})


def test_structured_result_through_submit_result(openai_mock):
    openai_mock["replies"] = [[item({"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "enc"}),
                               call("submit_result", {"score": 87}), done(120)]]
    out = asyncio.run(ai.run("score this", system="sys", schema=SCHEMA, stage="triage", purpose="triage"))
    assert out["score"] == 87 and out["_tokens"] == 120
    body = openai_mock["bodies"][0]
    assert body["store"] is False and body["stream"] is True and body["model"] == "gpt-test"
    assert body["tools"][0]["type"] == "namespace" and body["tools"][0]["tools"][0]["name"] == "submit_result"
    assert "reasoning.encrypted_content" in body["include"] and body["reasoning"] == {"effort": "low"}
    assert not any(k in body for k in ("temperature", "max_output_tokens", "previous_response_id"))


def test_web_task_fetches_pages_and_falls_back_without_search(openai_mock, monkeypatch):
    async def fake_fetch(url):
        return f"HTTP 200 {url}\n\nJob posting text"
    monkeypatch.setattr(ai, "fetch_public", fake_fetch)
    refused = httpx.Response(400, json={"error": {"message": "web_search is not supported for this account", "code": "invalid_request"}})
    openai_mock["replies"] = [refused, [call("fetch_url", {"url": "https://example.com/job"}), done(30)],
                              [call("submit_result", {"score": 70}, "c2"), done(40)]]
    out = asyncio.run(ai.run("find jobs", system="sys", schema=SCHEMA, stage="hunt", purpose="hunt", web=True))
    assert out["score"] == 70 and out["_tools"]["pages"] == 1 and ai.web_search_ok is False
    first, retry, second = openai_mock["bodies"]
    assert any(t.get("type") == "web_search" for t in first["tools"])
    assert not any(t.get("type") == "web_search" for t in retry["tools"])
    replay = second["input"]
    assert replay[1] == {"type": "function_call", "call_id": "c1", "name": "fetch_url", "arguments": json.dumps({"url": "https://example.com/job"}),
                         "namespace": "jobportal"}  # replayed without its server id
    assert replay[2]["type"] == "function_call_output" and "Job posting text" in replay[2]["output"]


def test_a_search_refusal_without_search_is_an_error_not_a_retry(openai_mock):
    openai_mock["replies"] = [httpx.Response(400, json={"error": {"message": "web_search is not supported for this account"}})]
    with pytest.raises(ai.AIError, match="web_search"):
        asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))
    assert len(openai_mock["bodies"]) == 1


def test_missing_fields_get_a_second_chance(openai_mock):
    openai_mock["replies"] = [[call("submit_result", {}), done()], [call("submit_result", {"score": 5}, "c2"), done()]]
    assert asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))["score"] == 5
    assert "Missing required fields: score" in openai_mock["bodies"][1]["input"][-1]["output"]


def test_bad_tool_calls_get_a_reply(openai_mock):
    not_an_object = item({"type": "function_call", "call_id": "c1", "name": "submit_result", "arguments": "[1, 2]"})
    openai_mock["replies"] = [[not_an_object, call("send_email", {}, "c2"), done()], [call("submit_result", {"score": 3}, "c3"), done()]]
    assert asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))["score"] == 3
    replies = [i["output"] for i in openai_mock["bodies"][1]["input"] if i["type"] == "function_call_output"]
    assert "valid JSON object" in replies[0] and "no tool called send_email" in replies[1]


def test_a_failed_task_still_logs_its_tokens(openai_mock):
    failed = {"type": "response.failed", "response": {"error": {"code": "server_error", "message": "boom"}}}
    openai_mock["replies"] = [[call("send_email", {}), done(40)], [failed]]
    with pytest.raises(ai.AIError, match="server_error: boom"):
        asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))
    assert db.one("SELECT tokens, ok, error FROM ai_calls") == {"tokens": 40, "ok": 0, "error": "server_error: boom"}
    assert bus.state["tokens"] == 40


def test_usage_cap_and_plan_errors(openai_mock):
    openai_mock["replies"] = [[{"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded",
                                                                                   "message": "cap"}}}]]
    with pytest.raises(ai.UsageLimitError):
        asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))
    assert ai.usage_high()
    openai_mock["replies"] = [httpx.Response(403, json={"error": {"code": "subscription_sharing_user_not_eligible", "message": "no"}})]
    with pytest.raises(ai.AIError, match="Go, Plus or Pro"):
        asyncio.run(ai.run("x", system="s", schema=SCHEMA, stage="triage", purpose="t"))


def test_models_are_listed_for_the_account(openai_mock):
    assert asyncio.run(ai.models()) == ["gpt-test"]


def test_fetch_refuses_local_private_and_malformed_addresses():
    urls = ("http://127.0.0.1:8788/api/settings", "http://localhost/", "http://192.168.1.10/", "http://[::1]/", "file:///etc/passwd",
            "http://[::1", "http://example.com:99999/", f"http://{'a' * 64}.com/")
    for url in urls:
        text = asyncio.run(ai.fetch_public(url))  # always a reply for the model, never an exception
        assert any(s in text for s in ("can't be fetched", "Only public", "isn't a valid URL")), url
