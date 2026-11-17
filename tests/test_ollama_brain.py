"""Ollama brain: local HTTP client, fake Ollama server, no real network."""

import json

import httpx
import pytest

from sellbird.ollama_brain import OllamaBrain


def _fake_ollama(answer="Hello from local Qwen.", models=("qwen3:0.6b",)):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in models]})
        if request.url.path == "/api/chat":
            body = json.loads(request.content)
            assert body["model"] == "qwen3:0.6b"
            assert body["stream"] is False
            return httpx.Response(200, json={
                "message": {"role": "assistant", "content": "<think>reasoning</think>\n" + answer},
                "prompt_eval_count": 10, "eval_count": 5, "done": True,
            })
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _brain(tmp_path, transport=None):
    client = httpx.AsyncClient(transport=transport or _fake_ollama(), base_url="http://localhost:11434")
    return OllamaBrain(host="http://localhost:11434", model="qwen3:0.6b",
                       client=client, log_path=tmp_path / "inference_log.jsonl")


@pytest.mark.asyncio
async def test_think_returns_model_text_without_think_block(tmp_path):
    brain = _brain(tmp_path)
    assert await brain.think("Say hello.") == "Hello from local Qwen."
    assert brain.last_reply_empty is False


@pytest.mark.asyncio
async def test_think_json_parses_json_response(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:0.6b"}]})
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": '{"subject": "Hi", "body": "Hello"}'},
            "done": True,
        })

    brain = _brain(tmp_path, httpx.MockTransport(handler))
    assert await brain.think_json("write an email") == {"subject": "Hi", "body": "Hello"}


@pytest.mark.asyncio
async def test_health_check_reports_model_present(tmp_path):
    brain = _brain(tmp_path)
    health = await brain.health_check()
    assert health["reachable"] is True
    assert health["model_present"] is True
    assert health["models_available"] == ["qwen3:0.6b"]


@pytest.mark.asyncio
async def test_unreachable_ollama_returns_empty_never_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    brain = _brain(tmp_path, httpx.MockTransport(handler))
    assert await brain.think("hello") == ""
    assert brain.last_reply_empty is True
    health = await brain.health_check()
    assert health["reachable"] is False
    assert health["error"]


@pytest.mark.asyncio
async def test_missing_model_returns_empty_and_health_says_so(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(404, json={"error": "model not found"})

    brain = _brain(tmp_path, httpx.MockTransport(handler))
    assert await brain.think("hello") == ""
    health = await brain.health_check()
    assert health["reachable"] is True  # server up, model missing
    assert health["model_present"] is False


@pytest.mark.asyncio
async def test_think_logs_inference_locally(tmp_path):
    brain = _brain(tmp_path)
    await brain.think("hello", agent="writer", task="personal_email")
    lines = (tmp_path / "inference_log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["model"] == "qwen3:0.6b"
    assert record["source"] == "ollama-local"
    assert record["ok"] is True
    assert record["host"] == "http://localhost:11434"
    # No API key or secret is ever logged.
    assert "key" not in json.dumps(record).lower() or "api" not in json.dumps(record).lower()


@pytest.mark.asyncio
async def test_think_uses_temperature_zero_and_keep_alive(tmp_path):
    """Deterministic generation: temperature 0 + keep_alive, verified 2026-11-17."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.update(body)
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": "ok"}, "done": True})

    brain = _brain(tmp_path, httpx.MockTransport(handler))
    assert await brain.think("hi") == "ok"
    assert seen["options"]["temperature"] == 0
    assert seen["keep_alive"] == "30m"
    assert brain.temperature == 0


@pytest.mark.asyncio
async def test_warmup_reports_warmed(tmp_path):
    brain = _brain(tmp_path)
    result = await brain.warmup()
    assert result["warmed"] is True
    assert result["model"] == "qwen3:0.6b"
    assert result["load_seconds"] is not None and result["load_seconds"] >= 0


@pytest.mark.asyncio
async def test_warmup_fails_cleanly_when_ollama_down(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    brain = _brain(tmp_path, httpx.MockTransport(handler))
    result = await brain.warmup()
    assert result["warmed"] is False
    assert result["error"]
