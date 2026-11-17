"""Local sales workflows (EDXSO fork) — all 8 assignment workflows.

Every workflow runs on data already stored locally (seeded sample data or a
company profiled earlier) and, when a model is needed, on the local Ollama
brain only. When Ollama is unreachable the workflow still completes using an
explicitly labelled deterministic template — the result is marked
``source: "deterministic-template"`` and says so in its text, so template
output is never presented as model output. No workflow ever makes an
external HTTP call or a paid API call.

Each result carries ``workflow``, ``model`` (or ``null`` for templates),
``source`` (``ollama-local`` | ``deterministic-template``), ``timestamp``,
and the payload, and is appended to ``data/inference_log.jsonl`` via
``sellbird.ollama_brain.log_inference``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sellbird.ollama_brain import OllamaBrain, log_inference

WORKFLOWS = (
    "business_profile",
    "icp_generation",
    "prospect_research",
    "buying_signal_classification",
    "problem_statement",
    "personalised_email",
    "prospect_scoring",
    "reply_classification",
)

# Rule-based reply intents (used with or without a model; the model only
# refines, the rules decide the label when they fire unambiguously).
_INTERESTED = ("interested", "yes", "let's talk", "book", "call", "demo", "pricing", "price", "send details", "tell me more")
_NOT_INTERESTED = ("not interested", "no thanks", "remove me", "don't contact", "stop emailing", "unsubscribe")
_OPTOUT = ("unsubscribe", "remove me", "opt out", "stop emailing", "do not contact", "gdpr", "delete my data")
_QUESTION = ("?", "how much", "how does", "what is", "can you", "do you offer")
_BOUNCE = ("undeliverable", "mailbox full", "address not found", "delivery failed", "message blocked")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(workflow: str, brain: OllamaBrain | None, ok: bool, extra: dict | None = None) -> None:
    record = {
        "ts": _now(),
        "workflow": workflow,
        "model": brain.model if brain else None,
        "host": brain.host if brain else None,
        "source": "ollama-local" if brain else "deterministic-template",
        "ok": ok,
    }
    if extra:
        record.update(extra)
    log_inference(record)


def _result(workflow: str, brain: OllamaBrain | None, payload: dict, used_llm: bool) -> dict:
    return {
        "workflow": workflow,
        "model": brain.model if (brain and used_llm) else None,
        "source": "ollama-local" if used_llm else "deterministic-template",
        "timestamp": _now(),
        **payload,
    }


async def _maybe_llm(brain: OllamaBrain | None, prompt: str, task: str) -> str:
    """LLM text, or ``""`` when there is no brain / Ollama is down."""
    if brain is None:
        return ""
    return await brain.think(prompt, agent="local_sales", task=task)


# ── 1. Business profile ──────────────────────────────────────────────

async def business_profile(company: dict, brain: OllamaBrain | None = None) -> dict:
    """One-paragraph profile of a company from its stored facts."""
    facts = (
        f"Company: {company.get('name')} ({company.get('domain')})\n"
        f"Industry: {company.get('industry')}; size: {company.get('company_size')}; "
        f"location: {company.get('location')}\n"
        f"Known facts: {company.get('description') or company.get('notes') or 'none stored'}"
    )
    text = await _maybe_llm(
        brain,
        f"Write a 3-sentence business profile from ONLY these stored facts. "
        f"Do not invent anything not stated.\n{facts}",
        "business_profile",
    )
    if text:
        _log("business_profile", brain, True, {"response_chars": len(text)})
        return _result("business_profile", brain, {"company": company.get("name"), "profile": text}, True)
    profile = (
        f"{company.get('name')} is a {company.get('company_size') or 'small'} "
        f"{company.get('industry') or 'organisation'} based in {company.get('location') or 'India'}. "
        f"{company.get('description') or ''} "
        "[Deterministic template — Ollama was unavailable, so no model wrote this.]"
    ).strip()
    _log("business_profile", None, True)
    return _result("business_profile", None, {"company": company.get("name"), "profile": profile}, False)


# ── 2. Product-specific ICP ──────────────────────────────────────────

def icp_for_product(product: dict) -> dict:
    """The ICP stored for a product, rendered as a workflow result (no LLM needed)."""
    icp = product.get("icp") or {}
    _log("icp_generation", None, True, {"product_id": product.get("id")})
    return _result(
        "icp_generation",
        None,
        {
            "product_id": product.get("id"),
            "product": product.get("name"),
            "icp": {
                "industries": icp.get("industries", []),
                "company_size": icp.get("company_size", ""),
                "titles": icp.get("titles", []),
                "geography": icp.get("geography", []),
                "hiring_signals": icp.get("hiring_signals", []),
            },
            "note": "ICP is configuration, not model output: it comes from the product definition in sellbird.yaml.",
        },
        False,
    )


# ── 3. Prospect research / enrichment ────────────────────────────────

async def enrich_prospect(prospect: dict, company: dict, brain: OllamaBrain | None = None) -> dict:
    """Summarise what is stored about a prospect; never invents contact facts."""
    stored = (
        f"Prospect: {prospect.get('first_name')} {prospect.get('last_name')} — "
        f"{prospect.get('title')} at {company.get('name')} ({company.get('domain')}). "
        f"Stored notes: {prospect.get('personalization_notes') or 'none'}. "
        f"Email: {prospect.get('email') or 'unknown'} "
        f"(status: {prospect.get('email_status') or 'guess'} — unverified addresses are never sent to)."
    )
    text = await _maybe_llm(
        brain,
        f"Summarise this prospect in 2 sentences for a sales rep, using ONLY the stored facts. "
        f"Flag anything missing rather than guessing it.\n{stored}",
        "prospect_research",
    )
    if text:
        _log("prospect_research", brain, True, {"response_chars": len(text)})
        return _result("prospect_research", brain, {"prospect": prospect.get("email"), "summary": text}, True)
    _log("prospect_research", None, True)
    return _result(
        "prospect_research",
        None,
        {"prospect": prospect.get("email"), "summary": stored + " [Deterministic template — no model used.]"},
        False,
    )


# ── 4. Buying-signal classification ──────────────────────────────────

BUYING_SIGNALS = ("HIRING_ROLE", "FUNDING", "NEW_LOCATION", "TECH_ADOPTION", "EXPANSION", "JOB_POSTING")


def classify_signals(observations: list[dict]) -> dict:
    """Classify stored observations into buying signals (rule-based, auditable)."""
    signals = []
    for obs in observations:
        code = (obs.get("signal_code") or "").upper()
        if code in BUYING_SIGNALS or code.startswith("HIRING"):
            signals.append({"code": code, "detail": obs.get("value_text") or "", "observed_at": obs.get("observed_at")})
    _log("buying_signal_classification", None, True, {"signals": len(signals)})
    return _result(
        "buying_signal_classification",
        None,
        {"signals": signals, "count": len(signals), "in_market": bool(signals)},
        False,
    )


# ── 5. Problem statement ─────────────────────────────────────────────

async def problem_statement(company: dict, product: dict, signals: list[dict], brain: OllamaBrain | None = None) -> dict:
    """The problem the product solves for this company, grounded in its signals."""
    signal_text = "; ".join(s.get("detail") or s.get("code") for s in signals) or "no buying signals stored"
    prompt = (
        f"Company {company.get('name')} ({company.get('industry')}, {company.get('company_size')}) "
        f"shows these signals: {signal_text}. Product: {product.get('name')} — "
        f"{product.get('description')}. Write ONE problem statement (2 sentences max) "
        f"linking the company's situation to the product. Only use the facts given."
    )
    text = await _maybe_llm(brain, prompt, "problem_statement")
    if text:
        _log("problem_statement", brain, True, {"response_chars": len(text)})
        return _result("problem_statement", brain, {"company": company.get("name"), "product_id": product.get("id"), "statement": text}, True)
    statement = (
        f"{company.get('name')} is a {company.get('company_size') or ''} {company.get('industry') or 'organisation'} "
        f"showing: {signal_text}. {product.get('name')} addresses this by "
        f"{(product.get('key_benefits') or [''])[0].lower() if product.get('key_benefits') else 'automating manual work'}. "
        "[Deterministic template — Ollama was unavailable.]"
    )
    _log("problem_statement", None, True)
    return _result("problem_statement", None, {"company": company.get("name"), "product_id": product.get("id"), "statement": statement}, False)


# ── 6. Personalised email ────────────────────────────────────────────

async def personalised_email(prospect: dict, company: dict, product: dict, statement: str, brain: OllamaBrain | None = None) -> dict:
    """Short cold email grounded in stored facts + the problem statement."""
    prompt = (
        f"Write a cold email under 75 words to {prospect.get('first_name')} "
        f"({prospect.get('title')} at {company.get('name')}) about {product.get('name')} "
        f"({product.get('description')}; {product.get('pricing')}). "
        f"Open with this problem: {statement} "
        f"End with one question. No invented facts, no fake social proof. "
        f"Subject line first, on its own line starting 'Subject:'."
    )
    text = await _maybe_llm(brain, prompt, "personalised_email")
    if text:
        _log("personalised_email", brain, True, {"response_chars": len(text)})
        subject, _, body = text.partition("\n")
        # The 0.6b model often wraps the subject in markdown artefacts
        # ("**** Need for …", "**Subject:** …"). Strip them deterministically;
        # the wording stays the model's.
        subject = subject.replace("Subject:", "").strip().strip("*#\"' ").strip()
        subject = re.sub(r"\s+", " ", subject)
        return _result("personalised_email", brain,
                       {"to": prospect.get("email"), "product_id": product.get("id"),
                        "subject": subject, "body": body.strip() or text}, True)
    body = (
        f"Hi {prospect.get('first_name')},\n\n{statement}\n\n"
        f"{product.get('name')} helps {company.get('industry') or 'organisations like yours'} with "
        f"{', '.join((product.get('key_benefits') or [])[:2]).lower() or 'the manual work'}. "
        f"{product.get('pricing', '')} — would a 15-minute look be useful?\n\n"
        f"Best regards\n[Deterministic template — Ollama was unavailable; review before sending.]"
    )
    _log("personalised_email", None, True)
    return _result("personalised_email", None,
                   {"to": prospect.get("email"), "product_id": product.get("id"),
                    "subject": f"Quick question about {company.get('name')}", "body": body}, False)


# ── 7. Prospect scoring (per product) ────────────────────────────────

def score_prospect(company: dict, prospects: list[dict], observations: list[dict], product: dict) -> dict:
    """Per-product 0-100 fit score via ``sellbird.fit.product_fit``."""
    from sellbird.fit import product_fit

    score, reasons = product_fit(company, prospects, observations, product)
    _log("prospect_scoring", None, True, {"score": score, "product_id": product.get("id")})
    return _result(
        "prospect_scoring",
        None,
        {"company": company.get("name"), "product_id": product.get("id"), "score": score, "reasons": reasons},
        False,
    )


# ── 8. Reply classification ──────────────────────────────────────────

# Strict few-shot prompt for the LLM classifier. Verified 2026-11-17:
# qwen3:0.6b with a loose prompt ("Answer with one word") classified
# "Yes, please send pricing for 500 students." as 'needs info' (wrong).
# This prompt — exact-word answer, temperature 0 (see OllamaBrain), and
# four labelled examples — is the mitigation. The rule-based classifier
# below is always the fallback when the model answer is not one of the
# allowed words.
REPLY_INTENTS = ("interested", "question", "not_interested", "opt_out", "bounce", "other")

REPLY_CLASSIFY_PROMPT = """Classify the sales reply into exactly one intent.
Answer with exactly one of these words and nothing else — no quotes, no punctuation, no explanation:
interested, question, not_interested, opt_out, bounce, other

Rules:
- opt_out ONLY when the reply asks to be removed, unsubscribed, or to stop contact.
- Saying "not interested", "no thanks", or "already use another product" is not_interested, NOT opt_out.
- Asking for pricing, a demo, a call, or details is interested.

Examples:
Reply: "Yes, please send pricing for 500 students."
Answer: interested
Reply: "What is the pricing for two branches?"
Answer: question
Reply: "No thanks, we already use another ERP."
Answer: not_interested
Reply: "Please remove me from your list."
Answer: opt_out
Reply: "Not interested right now, please remove me from your list."
Answer: opt_out
Reply: "Thanks — this looks interesting, can we book a call next week?"
Answer: interested

Reply: "{reply}"
Answer:"""


async def classify_reply_llm(text: str, brain: OllamaBrain) -> dict:
    """LLM reply classification with the strict few-shot prompt.

    Measured 2026-11-17: qwen3:0.6b is unreliable on the
    not_interested/opt_out distinction even with temperature 0 and this
    prompt (it swapped the two labels between runs, and once called "No
    thanks, we already use another ERP." interested). So the RULE-based
    intent decides the final label — opt-out is a compliance label and a
    weak model must not override it. The model's answer is recorded as
    ``llm_intent`` (a second opinion) and its accuracy is reported
    separately by ``scripts/offline_test.py``. qwen3:1.7b classified the
    same sentences correctly, so it is the higher-accuracy option on
    machines with RAM to spare.
    """
    rule = classify_reply(text)
    raw = await brain.think(
        REPLY_CLASSIFY_PROMPT.format(reply=(text or "")[:500]),
        agent="local_sales", task="reply_classification_llm",
    )
    cleaned = (raw or "").strip().strip("'\"").strip().lower().split()[0:1]
    llm_intent = cleaned[0] if cleaned else ""
    if llm_intent not in REPLY_INTENTS:
        llm_intent = ""
    out = dict(rule)
    out["llm_intent"] = llm_intent or None
    out["rule_intent"] = rule["intent"]
    out["model"] = brain.model
    out["decision"] = "rule-based (LLM second opinion recorded)"
    return out


def classify_reply(text: str) -> dict:
    """Rule-based reply intent. Deterministic and auditable by design."""
    low = (text or "").lower()
    if any(p in low for p in _OPTOUT):
        intent, stage = "opt_out", "closed_out"
    elif any(p in low for p in _BOUNCE):
        intent, stage = "bounce", "closed_out"
    elif any(p in low for p in _NOT_INTERESTED):
        intent, stage = "not_interested", "closed_out"
    elif low.strip().startswith(("how ", "what ", "when ", "where ", "why ", "is ", "are ", "can you", "do you")):
        intent, stage = "question", "replied"
    elif any(p in low for p in _INTERESTED):
        intent, stage = "interested", "ready_to_meet"
    elif "?" in low:
        intent, stage = "question", "replied"
    elif not low.strip():
        intent, stage = "empty", "initial_outreach"
    else:
        intent, stage = "other", "replied"
    _log("reply_classification", None, True, {"intent": intent})
    return _result(
        "reply_classification",
        None,
        {"reply_excerpt": (text or "")[:200], "intent": intent, "stage": stage},
        False,
    )


async def run_all_workflows(seed: dict, brain: OllamaBrain | None = None) -> dict:
    """Run all 8 workflows over one seeded company/prospect/product set.

    ``seed``: ``{"company": {...}, "prospects": [...], "observations": [...],
    "product": {...}, "replies": [...]}``. Returns ``{workflow: result}``.
    """
    company = seed["company"]
    prospects = seed.get("prospects", [])
    observations = seed.get("observations", [])
    product = seed["product"]
    prospect = prospects[0] if prospects else {}
    out: dict = {}
    out["business_profile"] = await business_profile(company, brain)
    out["icp_generation"] = icp_for_product(product)
    out["prospect_research"] = await enrich_prospect(prospect, company, brain)
    signals = classify_signals(observations)
    out["buying_signal_classification"] = signals
    statement = await problem_statement(company, product, signals["signals"], brain)
    out["problem_statement"] = statement
    out["personalised_email"] = await personalised_email(
        prospect, company, product, statement["statement"], brain
    )
    out["prospect_scoring"] = score_prospect(company, prospects, observations, product)
    replies = seed.get("replies") or ["Thanks — this looks interesting, can we book a call next week?"]
    if brain is not None:
        # LLM classification (strict few-shot prompt) with the rule-based
        # result kept alongside for audit; rules decide if the model strays.
        out["reply_classification"] = await classify_reply_llm(replies[0], brain)
        out["reply_classifications_all"] = [
            await classify_reply_llm(r, brain) for r in replies
        ]
    else:
        out["reply_classification"] = classify_reply(replies[0])
        out["reply_classifications_all"] = [classify_reply(r) for r in replies]
    return out


def load_seed_json(path: str | Path) -> dict:
    """Load a seed file (the same shape ``seed.py`` writes)."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
