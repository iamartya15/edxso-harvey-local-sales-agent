"""Offline workflows: deterministic templates, reply rules, scoring."""

import json
from pathlib import Path

import pytest

from sellbird import local_sales

ROOT = Path(__file__).resolve().parent.parent


def _seed() -> dict:
    return json.loads((ROOT / "data" / "seed_sample_data.json").read_text())


@pytest.fixture(autouse=True)
def _no_log(monkeypatch):
    monkeypatch.setattr(local_sales, "log_inference", lambda *a, **k: None)


def _subset(seed, product_id):
    company = next(c for c in seed["companies"] if c["product_id"] == product_id)
    return {
        "company": company,
        "prospects": [p for p in seed["prospects"] if p["company_id"] == company["id"]],
        "observations": [o for o in seed["observations"] if o["company_id"] == company["id"]],
        "product": next(p for p in seed["products"] if p["id"] == product_id),
        "replies": [r["text"] for r in seed.get("sample_replies", [])],
    }


@pytest.mark.asyncio
async def test_all_eight_workflows_run_without_ollama():
    seed = _seed()
    results = await local_sales.run_all_workflows(_subset(seed, "school-erp"), brain=None)
    for name in local_sales.WORKFLOWS:
        assert name in results, f"missing workflow {name}"
        assert results[name]["source"] == "deterministic-template"
        assert "model" in results[name]
    assert results["prospect_scoring"]["score"] > 0
    assert results["personalised_email"]["body"]
    assert "Deterministic template" in results["personalised_email"]["body"]


@pytest.mark.asyncio
async def test_business_profile_is_labelled_template_when_offline():
    seed = _seed()
    company = seed["companies"][0]
    res = await local_sales.business_profile(company, brain=None)
    assert res["source"] == "deterministic-template"
    assert company["name"] in res["profile"]


def test_reply_classification_matches_labelled_samples():
    seed = _seed()
    for reply in seed["sample_replies"]:
        got = local_sales.classify_reply(reply["text"])
        assert got["intent"] == reply["expected_intent"], reply["text"]
    assert local_sales.classify_reply("Please unsubscribe me")["intent"] == "opt_out"
    assert local_sales.classify_reply("")["intent"] == "empty"


def test_buying_signal_classification_finds_hiring():
    seed = _seed()
    obs = [o for o in seed["observations"] if o["company_id"] == "co-02"]
    res = local_sales.classify_signals(obs)
    assert res["count"] == 2
    assert res["in_market"] is True
    assert local_sales.classify_signals([])["count"] == 0


def test_scoring_is_deterministic_and_bounded():
    seed = _seed()
    subset = _subset(seed, "college-attendance")
    a = local_sales.score_prospect(subset["company"], subset["prospects"],
                                   subset["observations"], subset["product"])
    b = local_sales.score_prospect(subset["company"], subset["prospects"],
                                   subset["observations"], subset["product"])
    assert a["score"] == b["score"]
    assert 0 <= a["score"] <= 100


def test_no_workflow_makes_external_calls(monkeypatch):
    """Guard: local_sales must not import or call any network client."""
    import sellbird.local_sales as ls

    assert not hasattr(ls, "httpx")
    assert "openai" not in dir(ls) and "anthropic" not in dir(ls)


@pytest.mark.asyncio
async def test_email_subject_markdown_artefacts_are_stripped(tmp_path):
    """0.6b wraps subjects in **** (live run 2026-11-17); wording stays the model's."""
    import httpx

    from sellbird.ollama_brain import OllamaBrain

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "message": {"role": "assistant",
                        "content": "**** Need for Centralized School ERP\n\nHi Anita,\n\nBody here."},
            "done": True})

    brain = OllamaBrain(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                 base_url="http://localhost:11434"),
        log_path=tmp_path / "l.jsonl")
    res = await local_sales.personalised_email(
        {"first_name": "Anita", "email": "a@sunrisepublic.test"},
        {"name": "Sunrise Public School", "industry": "K-12 School"},
        {"id": "school-erp", "name": "VidyaSetu School ERP",
         "description": "School ERP", "pricing": "Rs.4,999/month",
         "key_benefits": ["fee collection"]},
        "Sunrise lacks a central system.",
        brain,
    )
    assert res["subject"] == "Need for Centralized School ERP"
    assert "****" not in res["subject"]
    assert res["source"] == "ollama-local"
