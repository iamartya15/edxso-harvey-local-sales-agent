# Sellbird — Local Multi-Product AI Sales Agent (EDXSO Assignment 2 fork)

A fork of [Sellbird](https://github.com/ethanplusai/sellbird) (formerly Harvey, v0.4.0)
rebuilt for EDXSO Assignment 2 as a **fully local, multi-product AI sales agent**.

**What it is:** a FastAPI + SQLite sales agent that profiles businesses, builds a
product-specific ICP, researches prospects, classifies buying signals, writes a
problem statement, scores each prospect per product, drafts a personalised email,
and classifies replies — with all inference done by a local Ollama model
(Qwen3) on your own machine.

**What it is NOT:** it is not a cloud AI product. There is no OpenAI / Anthropic /
Gemini key, no Claude or ChatGPT subscription, no paid verifier, and no data
leaving the machine. When Ollama is unavailable, workflows fall back to
explicitly labelled deterministic templates — never to a silent cloud model.

## Quick start

```bash
# 1. Python env (Python 3.11+; tested on 3.12)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Ollama (one-time) — see docs/SETUP.md
ollama serve            # in one terminal
ollama pull qwen3:0.6b  # ~0.5 GB; qwen3:1.7b for 8-16 GB RAM, qwen3:4b for 16 GB+/GPU
python scripts/prewarm_model.py   # load the model once (~25 s cold) so the demo is warm

# 3. Seed the clearly-labelled SAMPLE data (fictional .test companies)
cp .env.example .env
python seed.py          # 3 products, 10 prospects, 8 observations, 5 sample replies

# 4. Run the offline acceptance test (no external HTTP at all)
python scripts/offline_test.py            # templates only
python scripts/offline_test.py --use-ollama   # real local inference, if Ollama is up

# 5. Dashboard
python -m sellbird dashboard   # http://127.0.0.1:5555 — try /api/local-health and /api/products
```

## The flow

1. **Business profile** — `sellbird/local_sales.py::business_profile` — a profile
   from stored company facts (Ollama, or a labelled template when Ollama is down).
2. **ICP generation** — per-product ICP from `sellbird.yaml` (`products[].icp`).
3. **Prospect research** — enrichment summary from stored notes only; nothing invented.
4. **Buying-signal classification** — rule-based on stored observations
   (e.g. `HIRING_ROLE: Admission Counsellor`).
5. **Problem statement** — links the company's signals to one product.
6. **Personalised email** — under 75 words, grounded in stored facts + the problem
   statement; subject line first.
7. **Prospect scoring** — 0–100 per product: sector 20 + decision-maker 30 +
   reachable 25 + buying signal 25 (`sellbird/fit.py::product_fit`).
8. **Reply classification** — rule-based intents: interested / question /
   not_interested / opt_out / bounce / empty.

Every workflow result carries `workflow`, `model`, `source`
(`ollama-local` | `deterministic-template`) and a timestamp, and is appended
to `data/inference_log.jsonl` (and the `inference_log` table) — see
`docs/OFFLINE_TEST.md`.

## Sample data

`data/seed_sample_data.json` — **SAMPLE, fictional.** Three products:

| Product | For | Price |
|---|---|---|
| VidyaSetu School ERP (`school-erp`) | K-12 schools | Rs.4,999/mo |
| ClassBook Coaching Suite (`coaching-booking`) | Tuition / coaching centres | Rs.2,499/mo |
| CampusTrack Attendance & Payroll (`college-attendance`) | Small colleges | Rs.149/employee/mo |

10 fictional prospects across them (all `.test` domains, e.g.
`anita.sharma@sunrisepublic.test`), all emails `email_status: guess`
(unverified — **never sent to**). 8 stored observations, 5 labelled sample
replies (reply classification is 5/5 on them — see `evidence/`).

## Tech

- **Upstream:** Sellbird 0.4.0 (AGPL-3.0-only), FastAPI + uvicorn dashboard,
  vanilla HTML/CSS/JS frontend, SQLite via aiosqlite, httpx + BeautifulSoup +
  Playwright scraping, prompts in `prompts/`, playbooks in `skills/`.
- **Fork changes:** `sellbird/ollama_brain.py` (Ollama HTTP brain, same
  `think()`/`think_json()` interface), `sellbird/local_sales.py` (the 8
  workflows), multi-product config (`products:` + per-product ICP) and schema
  migration v17 (`products` table, `product_id` columns, `inference_log`
  table), `/api/local-health` and `/api/products` dashboard endpoints,
  `seed.py`, `scripts/offline_test.py`, `scripts/hardware_check.py`.
- **What was NOT kept from upstream:** the Claude/Codex subscription brain
  (code retained, never selected — config defaults to `ollama`), and all
  optional paid services (Instantly, Reoon/ZeroBounce/Hunter, DataForSEO,
  Serper, Scavio, TrulyInbox, Precleared, Cloudflare). Only free paths
  remain: OpenStreetMap/Overpass discovery, DuckDuckGo/Bing fallback,
  DNS/MX-only email checks.
- **What was NOT built:** React frontend (upstream ships vanilla JS and it
  works — a rewrite would have risked the deadline for no functional gain)
  and Scrapy (upstream uses httpx/BeautifulSoup/Playwright, which already
  covers the scraping need). Both are documented as honest gaps in
  `docs/TECHNICAL.md`.

## Honest limitations

- **Real inference is proven, with measured caveats (2026-11-17).**
  Ollama 0.40.16 + `qwen3:0.6b` (522 MB, SHA-256-verified) and `qwen3:1.7b`
  (1.4 GB) are installed; `/api/generate` returned sensible answers for
  both. Default model is **qwen3:0.6b**, pre-warmed at startup
  (`python scripts/prewarm_model.py`): cold ~25 s, warm ~8 s per short
  call, llama-server RSS ~1,042 MiB. **qwen3:0.6b is weak at
  classification** — with a loose prompt it called "Yes, please send
  pricing for 500 students." `needs info` (wrong); the fork mitigates
  with temperature 0 + a strict few-shot prompt (exact-word answers) and
  a rule-based fallback, and `qwen3:1.7b` is documented as the
  higher-accuracy/slower option (correct classification, but 64.1 s cold,
  RSS ~1,807 MiB — effectively unworkable alongside FastAPI on this
  7.7 GB VM). Keep exactly one model loaded. See
  `evidence/ollama-smoke-test.md`.
- **`ollama pull` is blocked on this VM** (sentinel 403 on the registry
  token endpoint). Models were installed by the manual manifest/blob
  method (curl + SHA-256 verification into `~/.ollama/models/`); see
  `docs/SETUP.md`. Do not claim `ollama pull` works here. The model
  files are already in `~/.ollama/models/`, so the app does not need to
  pull again on this VM.
- Sample emails are **never sent**: addresses are unverified guesses and
  sending stays approval-gated (`channels.email.require_approval: true`).
- The 0.6B model is small: expect terse, sometimes generic copy. Use
  `qwen3:1.7b` on stronger hardware (see `scripts/hardware_check.py`).
- Upstream test suite: 3,682 passed / 40 failed on this machine — 39 are
  pre-existing environment failures (this VM's `NO_PROXY` breaks httpx
  proxy parsing; verified against pristine upstream) and 1 is an
  intentional fork break (the TrulyInbox affiliate-link test — the fork
  removes paid-service promotion on purpose). See `docs/TECHNICAL.md`.

## Docs

- `docs/SETUP.md` — Ollama install, model pull, hardware configs.
- `docs/TECHNICAL.md` — architecture, licences, what changed vs upstream.
- `docs/COST_AND_DEPENDENCIES.md` — zero-cost proof and how to verify it.
- `docs/OFFLINE_TEST.md` — the offline acceptance test + manual procedure.
- `docs/DEMO_SCRIPT.md` — shot-by-shot 5–10 min demo recording script.
- `evidence/` — offline-test reports, hardware check, Ollama status.

## Licence

GNU AGPL-3.0-only (upstream Sellbird 0.4.0; see `LICENSE` and `NOTICE`).
This fork keeps the AGPL licence and upstream attribution; it is **not**
re-licensed. Qwen3 model licence: Apache 2.0 (see `docs/TECHNICAL.md`).
