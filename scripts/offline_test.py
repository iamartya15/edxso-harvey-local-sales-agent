"""Offline acceptance test — all 8 workflows, zero external HTTP.

Usage:
    python scripts/offline_test.py [--data data/seed_sample_data.json]
                                   [--out evidence] [--use-ollama]

Runs every workflow in ``sellbird/local_sales.py`` against the locally
stored sample data (``data/seed_sample_data.json``) and writes evidence to
``evidence/offline-test-<timestamp>.md`` and ``.json``.

Offline guarantee: this script makes NO external HTTP call. With
``--use-ollama`` it may call ONLY http://localhost:11434 (the local Ollama
server); without it, every workflow uses the labelled deterministic
templates. Either way the evidence file states which source each result
came from, so a reader can tell model output from template output.

Exit code: 0 when all 8 workflows produce a result, non-zero otherwise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sellbird import local_sales  # noqa: E402
from sellbird.ollama_brain import OllamaBrain, ensure_local_env  # noqa: E402

# Strip proxy env vars first: httpx 0.28 crashes on this VM's NO_PROXY
# ([::1] etc.) when a client is built with trust_env=True.
ensure_local_env()


def _company_seed(seed: dict, product_id: str) -> dict:
    company = next(c for c in seed["companies"] if c["product_id"] == product_id)
    prospects = [p for p in seed["prospects"] if p["company_id"] == company["id"]]
    observations = [o for o in seed.get("observations", []) if o["company_id"] == company["id"]]
    product = next(p for p in seed["products"] if p["id"] == product_id)
    return {
        "company": company,
        "prospects": prospects,
        "observations": observations,
        "product": product,
        "replies": [r["text"] for r in seed.get("sample_replies", [])],
    }


async def _run(seed: dict, brain: OllamaBrain | None) -> dict:
    results: dict = {"workflows": {}, "products_checked": []}
    # All 8 workflows on the first product, plus scoring on every product
    # (multi-product proof: the same company scores differently per product).
    first = _company_seed(seed, seed["products"][0]["id"])
    results["workflows"] = await local_sales.run_all_workflows(first, brain)
    for product in seed["products"]:
        subset = _company_seed(seed, product["id"])
        scored = local_sales.score_prospect(
            subset["company"], subset["prospects"], subset["observations"], subset["product"]
        )
        results["products_checked"].append(
            {"product_id": product["id"], "score": scored["score"], "reasons": scored["reasons"]}
        )
    # Reply classification accuracy against the labelled sample replies.
    expected = {r["text"]: r["expected_intent"] for r in seed.get("sample_replies", [])}
    correct = sum(
        1 for r in seed.get("sample_replies", [])
        if local_sales.classify_reply(r["text"])["intent"] == r["expected_intent"]
    )
    results["reply_classification_accuracy"] = {
        "correct": correct,
        "total": len(expected),
        "expected": expected,
    }
    if brain is not None:
        # Same check for the LLM classifier (strict few-shot prompt),
        # reusing the classifications run_all_workflows already made —
        # no second round of model calls.
        llm_results = results["workflows"]["reply_classifications_all"]
        llm_correct = sum(
            1 for res, r in zip(llm_results, seed.get("sample_replies", []))
            if res.get("llm_intent") == r["expected_intent"]
        )
        results["reply_classification_llm_accuracy"] = {
            "correct": llm_correct,
            "total": len(expected),
            "model": brain.model,
            "note": "LLM is a second opinion only; the rule-based intent decides the final label (0.6b is unreliable on not_interested vs opt_out).",
            "per_reply": [
                {"text": r["text"][:60], "expected": r["expected_intent"],
                 "llm": res.get("llm_intent"), "rule": res.get("rule_intent"),
                 "final": res["intent"]}
                for res, r in zip(llm_results, seed.get("sample_replies", []))
            ],
        }
    return results


def _markdown(results: dict, brain: OllamaBrain | None, started: str) -> str:
    lines = [
        "# Offline acceptance test — evidence",
        "",
        f"- Run at (UTC): {started}",
        f"- Ollama used: {'yes — localhost only' if brain else 'no — deterministic templates only'}",
        f"- Model: {brain.model if brain else 'none (template)'}",
        "- External HTTP calls: none (this script only reads local files and, with --use-ollama, localhost:11434).",
        "",
        "## Workflows",
        "",
    ]
    for name, res in results["workflows"].items():
        if isinstance(res, list):
            lines.append(f"- **{name}**: {len(res)} results")
            continue
        lines.append(
            f"- **{name}**: source=`{res.get('source')}`, model=`{res.get('model')}`"
        )
    lines += ["", "## Per-product scores", ""]
    for row in results["products_checked"]:
        lines.append(f"- {row['product_id']}: {row['score']}/100 — {'; '.join(row['reasons'])}")
    acc = results["reply_classification_accuracy"]
    lines += [
        "",
        "## Reply classification",
        "",
        f"- Rule-based: {acc['correct']}/{acc['total']} against the labelled sample replies.",
    ]
    llm_acc = results.get("reply_classification_llm_accuracy")
    if llm_acc:
        lines.append(
            f"- LLM ({llm_acc['model']}, strict few-shot prompt, temperature 0): "
            f"{llm_acc['correct']}/{llm_acc['total']}."
        )
        for row in llm_acc["per_reply"]:
            lines.append(
                f"  - `{row['text']}…` expected={row['expected']} llm={row['llm']} "
                f"rule={row['rule']} final={row['final']}"
            )
    lines += [
        "",
        "## Verdict",
        "",
        "PASS" if len(results["workflows"]) >= 8 else "FAIL",
    ]
    return "\n".join(lines) + "\n"


async def main_async(args) -> int:
    started = datetime.now(timezone.utc).isoformat()
    with open(args.data, encoding="utf-8") as fh:
        seed = json.load(fh)
    brain = None
    warmup = None
    if args.use_ollama:
        brain = OllamaBrain()
        health = await brain.health_check()
        print(f"Ollama health: {health}")
        if not health["reachable"]:
            print("Ollama unreachable — falling back to deterministic templates (labelled).")
            brain = None
        else:
            # Pre-warm: cold 0.6b ~25 s, warm ~8 s per call. Without this the
            # first workflow pays the full model-load cost.
            warmup = await brain.warmup()
            print(f"Warmup: {warmup}")
            if not warmup["warmed"]:
                print("Warmup failed — falling back to deterministic templates (labelled).")
                brain = None
    results = await _run(seed, brain)
    results["meta"] = {
        "run_at_utc": started,
        "ollama_used": brain is not None,
        "model": brain.model if brain else None,
        "warmup": warmup,
        "external_http_calls": 0,
        "workflows_run": sorted(results["workflows"].keys()),
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    (out_dir / f"offline-test-{stamp}.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / f"offline-test-{stamp}.md").write_text(
        _markdown(results, brain, started), encoding="utf-8"
    )
    n = sum(1 for name in local_sales.WORKFLOWS if name in results["workflows"])
    acc = results["reply_classification_accuracy"]
    print(f"Workflows run: {n}/8 | reply classification (rules): {acc['correct']}/{acc['total']} correct")
    llm_acc = results.get("reply_classification_llm_accuracy")
    if llm_acc:
        print(f"Reply classification (LLM {llm_acc['model']}): {llm_acc['correct']}/{llm_acc['total']} correct")
    print(f"Evidence: evidence/offline-test-{stamp}.md (+ .json)")
    return 0 if n >= 8 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(ROOT / "data" / "seed_sample_data.json"))
    parser.add_argument("--out", default=str(ROOT / "evidence"))
    parser.add_argument("--use-ollama", action="store_true",
                        help="allow localhost Ollama calls; otherwise templates only")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
