"""Runs Claude Code headlessly (`claude -p`) on the user's own logged-in account.

Every call is sandboxed to an empty scratch folder and gets at most WebSearch/WebFetch (no shell, no file writes), so
instructions planted in a job post or comment thread can't make the agent do anything beyond reading the web and returning
JSON. The system prompt goes through a temporary file and the user prompt through stdin, because Windows limits a command
line to about 32,000 characters and a full candidate profile is longer than that."""
import asyncio
import json
import os
import tempfile
import time
from itertools import count
from pathlib import Path

from . import bus, db, osutil
from . import settings as settings_mod
from .config import CACHE, WORKSPACE

_ids = count(1)
_sem: asyncio.Semaphore | None = None
_sem_size = 0
_procs: set[asyncio.subprocess.Process] = set()

NOT_INSTALLED = ("Claude Code isn't installed or isn't on your PATH. Install it from https://claude.com/claude-code, run `claude` "
                 "once in a terminal to log in, then try again (or set its full path in Settings -> AI).")


class ClaudeError(Exception):
    pass


class UsageLimitError(ClaudeError):
    pass


def _semaphore(n: int) -> asyncio.Semaphore:
    global _sem, _sem_size
    if _sem is None or _sem_size != n:
        _sem, _sem_size = asyncio.Semaphore(n), n
    return _sem


def claude_cmd(cfg: dict) -> list[str]:
    return osutil.claude_command(cfg["ai"].get("claude_bin") or "claude")


def kill_all() -> None:
    for p in list(_procs):
        try:
            p.kill()
        except ProcessLookupError:
            pass


def _describe_tool(name: str, inp: dict) -> str:
    if name == "WebSearch":
        return f"search: {inp.get('query', '')}"
    if name == "WebFetch":
        return f"read: {inp.get('url', '')}"
    return name


async def run(prompt: str, *, system: str, schema: dict, stage: str, purpose: str,
              tools: list[str] | None = None, run_id: int | None = None, lead_id: int | None = None,
              timeout: int = 1200, label: str | None = None) -> dict:
    """Run one headless Claude call and return its validated structured output.

    `stage` picks the model/effort pair from settings (prefill, triage, hunt, package, revise, profile, analysis)."""
    cfg = settings_mod.get()
    ai = cfg["ai"]
    st = ai["stages"].get(stage, {"model": "sonnet", "effort": "medium"})
    model, effort = st["model"], st["effort"]
    tools = tools or []
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    fd, sys_path = tempfile.mkstemp(prefix="system-", suffix=".txt", dir=CACHE)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(system)
    cmd = [*claude_cmd(cfg), "-p",
           "--model", model, "--effort", effort,
           "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "--safe-mode", "--strict-mcp-config",
           "--system-prompt-file", sys_path,
           "--json-schema", json.dumps(schema, separators=(",", ":")),
           "--permission-mode", "dontAsk",
           "--tools", ",".join(tools)]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if ai.get("budget_per_call_usd"):
        cmd += ["--max-budget-usd", str(ai["budget_per_call_usd"])]

    env = dict(os.environ)
    if ai.get("strip_api_key", True):
        env.pop("ANTHROPIC_API_KEY", None)  # bill the logged-in subscription, not an API key

    agent_id = next(_ids)
    label = label or purpose
    t0 = time.time()
    result: dict | None = None
    err: str | None = None
    tool_counts: dict[str, int] = {}
    proc = None
    stderr = ""
    try:
        async with _semaphore(max(1, int(ai.get("max_parallel", 3)))):
            bus.state["active_agents"][agent_id] = f"{label} ({model}/{effort})"
            bus.publish("agents", bus.state["active_agents"])
            try:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, cwd=str(WORKSPACE), env=env, limit=64 * 1024 * 1024,
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        **osutil.popen_flags())
                except FileNotFoundError:
                    raise ClaudeError(NOT_INSTALLED) from None
                _procs.add(proc)
                stderr_task = asyncio.create_task(proc.stderr.read())  # drain concurrently so stderr can't block
                try:
                    proc.stdin.write(prompt.encode("utf-8"))
                    await proc.stdin.drain()
                    proc.stdin.close()

                    async def pump():
                        nonlocal result
                        async for raw in proc.stdout:
                            try:
                                ev = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            t = ev.get("type")
                            if t == "assistant":
                                for c in ev.get("message", {}).get("content", []):
                                    if c.get("type") == "tool_use" and c.get("name") in ("WebSearch", "WebFetch"):
                                        tool_counts[c["name"]] = tool_counts.get(c["name"], 0) + 1
                                        bus.publish("log", {"run_id": run_id, "source": label, "level": "agent",
                                                            "msg": _describe_tool(c["name"], c.get("input", {}))})
                            elif t == "rate_limit_event":
                                info = ev.get("rate_limit_info", {})
                                bus.state["usage"] = info
                                bus.publish("usage", info)
                                db.kv_set("usage", info)  # survives restarts so the sidebar meter isn't blank
                            elif t == "result":
                                result = ev

                    await asyncio.wait_for(pump(), timeout=timeout)
                    await proc.wait()
                    stderr = (await stderr_task).decode(errors="ignore")[-2000:]
                except asyncio.TimeoutError:
                    proc.kill()
                    err = f"timed out after {timeout}s"
                except asyncio.CancelledError:
                    proc.kill()
                    raise
                finally:
                    _procs.discard(proc)
            finally:
                bus.state["active_agents"].pop(agent_id, None)
                bus.publish("agents", bus.state["active_agents"])
    finally:
        Path(sys_path).unlink(missing_ok=True)

    cost = float((result or {}).get("total_cost_usd") or 0)
    if result is None and not err:
        hint = stderr.strip()[-400:]
        if "login" in hint.lower() or "auth" in hint.lower():
            hint += " (run `claude` once in a terminal to log in)"
        err = f"no result from claude (exit {proc.returncode if proc else '?'}): {hint}"
    elif result is not None and (result.get("is_error") or result.get("subtype") != "success"):
        err = f"{result.get('subtype')}: {str(result.get('result') or result.get('errors') or '')[:400]}"
    out = (result or {}).get("structured_output")
    if not err and out is None:
        # Fall back to parsing a JSON object out of the text result.
        txt = (result or {}).get("result") or ""
        try:
            out = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError):
            err = "model returned no structured output"

    db.ex("INSERT INTO ai_calls(ts,run_id,lead_id,purpose,model,effort,cost_usd,duration_ms,ok,error) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (db.now(), run_id, lead_id, purpose, model, effort, cost, int((time.time() - t0) * 1000), 0 if err else 1, err))
    bus.state["cost_usd"] = round(bus.state.get("cost_usd", 0) + cost, 4)
    bus.publish("cost", bus.state["cost_usd"])
    if err:
        low = err.lower()
        if any(s in low for s in ("usage limit", "rate limit", "limit reached", "rate_limit", "out of credits", "overloaded")):
            raise UsageLimitError(err)
        raise ClaudeError(err)
    out["_cost_usd"] = cost
    out["_tools"] = tool_counts
    return out


def usage_high(cfg: dict) -> bool:
    info = bus.state.get("usage") or {}
    if info.get("status") and info["status"] not in ("allowed", "allowed_warning"):
        return True
    five = (info.get("unifiedWindows") or {}).get("five_hour", {}).get("utilization")
    return five is not None and five >= float(cfg["ai"].get("pause_at_5h_utilization", 0.92))
