"""Seed the local database with clearly labelled SAMPLE data.

Usage:
    python seed.py [--db data/sellbird.db] [--data data/seed_sample_data.json]

Loads ``data/seed_sample_data.json`` — 3 fictional products, 10 fictional
companies/prospects (all ``.test`` domains), stored observations and sample
replies — into the Sellbird SQLite database. Idempotent (INSERT OR REPLACE).
Nothing here is a real company: every row is marked ``source='sample'`` and
every email is ``email_status='guess'`` (unverified — never sent to).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sellbird.state import StateManager  # noqa: E402


def load_seed(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def seed(db_path: Path, seed: dict) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(StateManager(str(db_path)).init_db())
    con = sqlite3.connect(str(db_path))
    try:
        counts = {}
        for product in seed["products"]:
            con.execute(
                """INSERT OR REPLACE INTO products
                   (id, name, description, pricing, key_benefits_json,
                    objection_responses_json, offer_json, icp_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    product["id"],
                    product["name"],
                    product["description"],
                    product["pricing"],
                    json.dumps(product["key_benefits"]),
                    json.dumps(product["objection_responses"]),
                    json.dumps(product["offer"]),
                    json.dumps(product["icp"]),
                ),
            )
        counts["products"] = len(seed["products"])

        for company in seed["companies"]:
            con.execute(
                """INSERT OR REPLACE INTO companies
                   (id, name, domain, website, description, industry,
                    company_size, location, source, notes, product_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    company["id"],
                    company["name"],
                    company["domain"],
                    f"https://{company['domain']}",
                    company["description"],
                    company["industry"],
                    company["company_size"],
                    company["location"],
                    "sample",
                    "SAMPLE DATA — fictional company (see data/seed_sample_data.json).",
                    company["product_id"],
                ),
            )
        counts["companies"] = len(seed["companies"])

        for prospect in seed["prospects"]:
            con.execute(
                """INSERT OR REPLACE INTO prospects
                   (id, company_id, first_name, last_name, email, email_verified,
                    email_status, title, source, status, personalization_notes, company,
                    industry, company_size, product_id)
                   VALUES (?, ?, ?, ?, ?, 0, 'guess', ?, 'sample', ?, ?, ?, ?, ?, ?)""",
                (
                    prospect["id"],
                    prospect["company_id"],
                    prospect["first_name"],
                    prospect["last_name"],
                    prospect["email"],
                    prospect["title"],
                    prospect["status"],
                    prospect["personalization_notes"],
                    next(
                        (c["name"] for c in seed["companies"] if c["id"] == prospect["company_id"]),
                        "",
                    ),
                    next(
                        (c["industry"] for c in seed["companies"] if c["id"] == prospect["company_id"]),
                        "",
                    ),
                    next(
                        (c["company_size"] for c in seed["companies"] if c["id"] == prospect["company_id"]),
                        "",
                    ),
                    prospect["product_id"],
                ),
            )
        # email_status='guess' is set in the INSERT above: unverified
        # addresses are never sent to (see docs/COST_AND_DEPENDENCIES.md).
        counts["prospects"] = len(seed["prospects"])

        for code, label in (
            ("HIRING_ROLE", "Open role matching the product ICP"),
            ("DECISION_MAKER_TITLE", "Named decision-maker title seen on the company site"),
        ):
            con.execute(
                """INSERT OR REPLACE INTO signal_codes
                   (code, label, description, category, value_type, collector, status)
                   VALUES (?, ?, ?, 'buying-signal', 'text', 'sample-seed', 'confirmed')""",
                (code, label, label),
            )

        for i, obs in enumerate(seed.get("observations", [])):
            con.execute(
                """INSERT OR REPLACE INTO observations
                   (id, company_id, collector, signal_code, value_num, value_text, observed_at)
                   VALUES (?, ?, 'sample-seed', ?, ?, ?, ?)""",
                (
                    f"obs-{i + 1:02d}",
                    obs["company_id"],
                    obs["signal_code"],
                    obs.get("value_num", 0),
                    obs.get("value_text", ""),
                    obs.get("observed_at", "2026-11-17T10:00:00Z"),
                ),
            )
        counts["observations"] = len(seed.get("observations", []))

        for i, reply in enumerate(seed.get("sample_replies", [])):
            thread = [
                {"role": "assistant", "content": "Sample outreach email (template, never sent)."},
                {"role": "user", "content": reply["text"]},
            ]
            con.execute(
                """INSERT OR REPLACE INTO conversations
                   (id, prospect_id, channel, thread_json, intent, stage, status, product_id)
                   VALUES (?, ?, 'email', ?, ?, ?, 'open', ?)""",
                (
                    f"conv-{i + 1:02d}",
                    reply["prospect_id"],
                    json.dumps(thread),
                    reply["expected_intent"],
                    {"interested": "ready_to_meet", "question": "replied"}.get(
                        reply["expected_intent"], "closed_out"
                    ),
                    next(
                        (p["product_id"] for p in seed["prospects"] if p["id"] == reply["prospect_id"]),
                        "",
                    ),
                ),
            )
        counts["conversations"] = len(seed.get("sample_replies", []))
        con.commit()
    finally:
        con.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "data" / "sellbird.db"))
    parser.add_argument("--data", default=str(ROOT / "data" / "seed_sample_data.json"))
    args = parser.parse_args()
    seed_data = load_seed(Path(args.data))
    counts = seed(Path(args.db), seed_data)
    print(f"Seeded {args.db}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print("SAMPLE DATA — fictional .test companies only; emails are unverified guesses, never sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
