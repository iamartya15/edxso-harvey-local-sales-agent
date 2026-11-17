"""Ollama brain — Sellbird's thinking engine, local-only (EDXSO fork).

Replaces the upstream Claude/Codex subscription CLIs (``sellbird/brain.py``,
``sellbird/claude_runtime.py``, ``sellbird/codex.py``) with a plain HTTP
client for a locally running Ollama server. Same ``think()`` /
``think_json()`` interface so existing agents can call it unchanged.

- Default model ``qwen3:0.6b`` on ``http://localhost:11434`` (env
  ``OLLAMA_HOST`` / ``OLLAMA_MODEL``, or ``brain:`` in sellbird.yaml).
- NO cloud fallback: if Ollama is unreachable, ``think()`` returns ``""``
  and ``health_check()`` reports ``reachable: false``. Callers that need an
  answer anyway must use the explicitly labelled deterministic templates in
  ``sellbird/local_sales.py`` — never a silent remote model.
- Every call is appended to ``data/inference_log.jsonl`` (model, host,
  prompt hash, latency, token counts when reported, timestamp) so a run can
  be audited as local inference.
- No API key of any kind is read, sent, or stored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger("sellbird.ollama_brain")

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:0.6b"
DEFAULT_TIMEOUT_SECONDS = 180.0
# Verified 2026-11-17: qwen3:0.6b misclassifies with a loose prompt at
# temperature 0.6 (its Ollama default). Deterministic output (temperature 0)
# + strict few-shot prompts (see sellbird/local_sales.py) is the mitigation.
DEFAULT_TEMPERATURE = 0.0
# Keep the model loaded this long after the last call, so a demo does not
# pay the ~25 s cold-load cost on every workflow (0.6b cold 25.2 s, warm ~8 s).
DEFAULT_KEEP_ALIVE = "30m"

# Proxy env vars break httpx 0.28 at import/client-construction time in this
# VM (NO_PROXY holds bracketed IPv6 literals like [::1] -> "Invalid port:
# ':1]'"). The Ollama client never needs a proxy (localhost only), so it is
# built with trust_env=False; scripts that may import the `ollama` package
# should also call ensure_local_env() first (see below).
_PROXY_VARS = (
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY",
)


def ensure_local_env() -> None:
    """Remove proxy env vars from this process (localhost-only work).

    Call at the top of a script before importing the ``ollama`` package —
    ``import ollama`` crashes under the default env on this VM. The library
    itself does NOT mutate the environment; it relies on trust_env=False.
    """
    for var in _PROXY_VARS:
        os.environ.pop(var, None)


class OllamaUnavailable(Exception):
    """Ollama cannot be reached or has no usable model. No fallback exists."""


def _log_path() -> Path:
    """``data/inference_log.jsonl`` under the current Sellbird home."""
    try:
        from sellbird.workspace_home import current_home

        home = current_home()
        base = Path(getattr(home, "path", None) or getattr(home, "root", None) or Path.cwd())
    except Exception:
        base = Path.cwd()
    return Path(base) / "data" / "inference_log.jsonl"


def log_inference(record: dict, log_path: Path | None = None) -> None:
    """Append one inference record (JSONL). Logging never breaks a call."""
    try:
        path = Path(log_path) if log_path else _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 - audit logging must not fail work
        logger.warning(f"Could not write inference log: {e}")


class OllamaBrain:
    """Thin async client for Ollama's ``/api/chat`` endpoint."""

    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
        log_path: Path | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
    ):
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self._client = client
        self.log_path = log_path
        self.temperature = temperature
        self.keep_alive = keep_alive
        self.last_reply_empty = False

    async def warmup(self) -> dict:
        """Load the model once (throwaway 1-word call) so later calls are warm.

        Verified timings (this VM): qwen3:0.6b cold ~25 s, warm ~8 s per
        short call. Returns ``{warmed, model, load_seconds, error}``.
        Call this at app/script startup, before any real workflow.
        """
        started = time.monotonic()
        result: dict = {"warmed": False, "model": self.model, "load_seconds": None, "error": ""}
        try:
            text = await self.think(
                "Reply with exactly one word: ok", agent="warmup", task="warmup"
            )
            result["warmed"] = bool(text)
            result["load_seconds"] = round(time.monotonic() - started, 1)
            if not text:
                result["error"] = "empty response from Ollama"
        except Exception as e:  # noqa: BLE001 - warmup reports, never raises
            result["error"] = str(e)[:300]
        return result

    async def health_check(self) -> dict:
        """``{reachable, host, model, models_available, error}`` — no prompt sent."""
        result: dict = {
            "reachable": False,
            "host": self.host,
            "model": self.model,
            "models_available": [],
            "error": "",
        }
        try:
            client = self._http()
            try:
                resp = await client.get("/api/tags", timeout=10.0)
                resp.raise_for_status()
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                result["models_available"] = models
                result["reachable"] = True
                result["model_present"] = self.model in models or any(
                    m.startswith(self.model.split(":")[0] + ":") for m in models
                )
                if not result["model_present"]:
                    result["error"] = f"model {self.model} not pulled on this host"
            finally:
                await self._close_owned(client)
        except Exception as e:  # noqa: BLE001 - health check reports, never raises
            result["error"] = str(e)[:300]
        return result

    def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        # trust_env=False: this client only ever talks to localhost, so it
        # must never consult proxy env vars — and this VM's NO_PROXY contains
        # bracketed IPv6 literals ([::1]) that httpx's env-proxy parsing
        # rejects with "Invalid port: ':1]'". (That same env bug breaks
        # upstream httpx clients in this VM; it is not a fork regression.)
        return httpx.AsyncClient(base_url=self.host, timeout=self.timeout, trust_env=False)

    async def _close_owned(self, client: httpx.AsyncClient) -> None:
        if client is not self._client:
            await client.aclose()

    async def think(
        self,
        prompt: str,
        session_id: str | None = None,
        expect_json: bool = False,
        timeout: float | None = None,
        agent: str = "",
        task: str = "",
    ) -> str:
        """Send ``prompt`` to the local model; ``""`` when Ollama is unusable.

        ``session_id``/``agent``/``task`` are accepted for interface
        compatibility with ``sellbird.brain.Brain`` and recorded in the log.
        """
        started = time.monotonic()
        record: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "workflow": task or agent or "think",
            "agent": agent,
            "model": self.model,
            "host": self.host,
            "source": "ollama-local",
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
            "prompt_chars": len(prompt),
            "ok": False,
        }
        try:
            client = self._http()
            try:
                payload: dict = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "keep_alive": self.keep_alive,
                    "options": {"temperature": self.temperature},
                }
                if expect_json:
                    payload["format"] = "json"
                resp = await client.post(
                    "/api/chat", json=payload, timeout=timeout or self.timeout
                )
                if resp.status_code == 404:
                    raise OllamaUnavailable(
                        f"model {self.model!r} not found on {self.host} "
                        f"(run: ollama pull {self.model})"
                    )
                resp.raise_for_status()
                data = resp.json()
            finally:
                await self._close_owned(client)
            text = (data.get("message") or {}).get("content", "") or ""
            # qwen3 emits a <think>…</think> block; keep only the answer.
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            record.update(
                {
                    "ok": bool(text),
                    "latency_s": round(time.monotonic() - started, 2),
                    "response_chars": len(text),
                    "prompt_tokens": (data.get("prompt_eval_count") or 0),
                    "response_tokens": (data.get("eval_count") or 0),
                }
            )
            self.last_reply_empty = not text
            return text
        except OllamaUnavailable:
            record["error"] = "model-not-found"
            self.last_reply_empty = True
            return ""
        except Exception as e:  # noqa: BLE001 - Ollama down is a normal state
            logger.error(f"Ollama call failed ({self.host}, {self.model}): {e}")
            record["error"] = str(e)[:300]
            self.last_reply_empty = True
            return ""
        finally:
            log_inference(record, self.log_path)

    async def think_json(
        self, prompt: str, session_id: str | None = None, agent: str = "", task: str = ""
    ) -> dict | list | None:
        """``think()`` with a JSON-only instruction; ``None`` on any failure."""
        full_prompt = prompt + "\n\nRespond ONLY with valid JSON. No markdown, no explanation."
        response = await self.think(
            full_prompt, session_id=session_id, expect_json=True, agent=agent, task=task
        )
        self.last_reply_empty = not response
        if not response:
            return None
        cleaned = re.sub(r"^```(?:json)?\s*", "", response.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start, end = cleaned.find(open_ch), cleaned.rfind(close_ch)
            if start != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1])
                except json.JSONDecodeError:
                    continue
        logger.error(f"Failed to parse JSON from Ollama brain: {response[:200]}")
        return None

    @staticmethod
    def _extract_json(text: str) -> dict | list | None:
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None
