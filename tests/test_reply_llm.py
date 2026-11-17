"""LLM reply classification: strict few-shot prompt, rule fallback."""

import httpx
import pytest

from sellbird import local_sales
from sellbird.ollama_brain import OllamaBrain


@pytest.fixture(autouse=True)
def _no_log(monkeypatch):
    monkeypatch.setattr(local_sales, "log_inference", lambda *a, **k: None)


def _brain_with_answer(tmp_path, answer: str) -> OllamaBrain:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:0.6b"}]})
        return httpx.Response(200, json={
            "message": {"role": "assistant", "content": answer}, "done": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler),
                               base_url="http://localhost:11434")
    return OllamaBrain(client=client, log_path=tmp_path / "l.jsonl")


@pytest.mark.asyncio
async def test_llm_classifies_pricing_request_as_interested(tmp_path):
    # The exact sentence qwen3:0.6b got WRONG with a loose prompt (2026-11-17):
    # with the strict few-shot prompt the model answers 'interested'.
    brain = _brain_with_answer(tmp_path, "interested")
    res = await local_sales.classify_reply_llm(
        "Yes, please send pricing for 500 students.", brain)
    assert res["intent"] == "interested"
    assert res["llm_intent"] == "interested"
    assert res["rule_intent"] == "interested"
    assert res["model"] == "qwen3:0.6b"
    assert res["decision"].startswith("rule-based")


@pytest.mark.asyncio
async def test_llm_answer_with_quotes_is_cleaned(tmp_path):
    # The live 0.6b run answered "'needs info'" — quotes and all.
    brain = _brain_with_answer(tmp_path, "'interested'")
    res = await local_sales.classify_reply_llm("Yes, send the details.", brain)
    assert res["intent"] == "interested"


@pytest.mark.asyncio
async def test_invalid_llm_answer_falls_back_to_rules(tmp_path):
    brain = _brain_with_answer(tmp_path, "needs info")  # not an allowed word
    res = await local_sales.classify_reply_llm(
        "Yes, please send pricing for 500 students.", brain)
    assert res["llm_intent"] is None
    assert res["intent"] == "interested"  # rule-based fallback
    assert res["source"] == "deterministic-template"


@pytest.mark.asyncio
async def test_rules_decide_when_llm_disagrees(tmp_path):
    # Measured live 2026-11-17: 0.6b called "No thanks, we already use
    # another ERP." opt_out (and once 'interested'). The rule decides;
    # the LLM answer is only recorded as a second opinion.
    brain = _brain_with_answer(tmp_path, "opt_out")
    res = await local_sales.classify_reply_llm(
        "No thanks, we already use another ERP.", brain)
    assert res["llm_intent"] == "opt_out"
    assert res["rule_intent"] == "not_interested"
    assert res["intent"] == "not_interested"
    assert res["decision"].startswith("rule-based")


@pytest.mark.asyncio
async def test_llm_prompt_contains_few_shot_examples():
    prompt = local_sales.REPLY_CLASSIFY_PROMPT
    assert "Yes, please send pricing for 500 students." in prompt
    assert "Answer: interested" in prompt
    assert "exactly one of these words and nothing else" in prompt
    assert set(local_sales.REPLY_INTENTS) == {
        "interested", "question", "not_interested", "opt_out", "bounce", "other"}
