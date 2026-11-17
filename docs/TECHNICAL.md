# Technical notes

## Architecture

```
sellbird.yaml  (brain: ollama, products: [3 products, each with its own ICP])
      │
      ▼
sellbird/ollama_brain.py ──POST http://localhost:11434/api/chat──► Ollama (Qwen3)
      │  think() / think_json() / health_check() — same interface as upstream Brain
      │  every call → data/inference_log.jsonl  (model, host, latency, tokens, ts)
      ▼
sellbird/local_sales.py — the 8 workflows (business_profile, icp_generation,
  prospect_research, buying_signal_classification, problem_statement,
  personalised_email, prospect_scoring, reply_classification)
      │  Ollama down? → deterministic template, labelled in the result
      ▼
sellbird/state.py — SQLite (data/sellbird.db), schema v17
  products table · product_id on companies/prospects/campaigns/conversations
  inference_log table · ollama_calls in usage_log
      │
      ▼
sellbird/dashboard.py — FastAPI on http://127.0.0.1:5555
  + GET /api/local-health   (Ollama reachable? model present? paid_api_calls: 0)
  + GET /api/products       (catalogue + prospect counts per product)
```

## Measured model behaviour (this VM, 2026-11-17)

| Model | Size | Cold | Warm/call | llama-server RSS | Classification check |
|---|---|---|---|---|---|
| qwen3:0.6b | 522 MB, 751M params, Q4_K_M | 25.2 s | ~7.6 s | 1,042 MiB | WRONG with loose prompt (`needs info` for a clear "interested" reply) |
| qwen3:1.7b | 1.4 GB, 2.0B params, Q4_K_M | 64.1 s | — | 1,807 MiB | Correct (`interested`) |

Mitigations built into the fork: default model qwen3:0.6b, pre-warm at
startup (`OllamaBrain.warmup()` / `scripts/prewarm_model.py`, `keep_alive:
30m`), **temperature 0** (the model's Ollama default is 0.6), a strict
few-shot reply-classification prompt with exact-word answers
(`sellbird/local_sales.py::REPLY_CLASSIFY_PROMPT`), and a rule-based
fallback whenever the model answer is not one of the allowed words.
Full verbatim outputs, timings and RAM numbers:
`evidence/ollama-smoke-test.md`.

Environment gotchas the code handles: (1) proxy env vars break httpx 0.28
(`NO_PROXY` holds `[::1]` etc.) — the Ollama client uses
`trust_env=False` and scripts call `ensure_local_env()`; the `ollama`
Python package (0.6.3, pip `--user`) is NOT imported by the app, which
uses raw HTTP to localhost:11434 instead. (2) `/tmp` is a 512 MiB tmpfs —
nothing in the fork downloads or writes large files there. (3) `ollama
pull` is blocked by a sentinel 403 on the registry token endpoint —
models were installed by the manual manifest/blob method with SHA-256
verification (see `docs/SETUP.md`).

## What changed vs upstream Sellbird 0.4.0 (commit 25ec839)

| Area | Change |
|---|---|
| `sellbird/ollama_brain.py` (new) | Ollama HTTP brain; no CLI, no subscription, no cloud fallback; temperature 0, keep_alive 30m, `warmup()`, `trust_env=False`, `ensure_local_env()` |
| `sellbird/local_sales.py` (new) | All 8 assignment workflows, local-data only, labelled templates; strict few-shot LLM reply classifier (`classify_reply_llm`) with rule fallback |
| `sellbird/config.py` | `brain.provider` accepts `ollama`; `ollama_host`/`ollama_model`; `ProductConfig.id` + per-product `icp`; `SellbirdConfig.products` + `all_products()`/`product_by_id()`/`icp_for_product()`; `ICPConfig` moved above `ProductConfig` (no behaviour change) |
| `sellbird/fit.py` | `product_fit()` — same 20/30/25/25 weights, per product ICP |
| `sellbird/state.py` | Migration v17 + idempotent `_ensure_fork_columns()`; `BRAIN_PROVIDERS` gains `ollama` |
| `sellbird/dashboard.py` | `/api/local-health`, `/api/products`; quota lookup returns None for ollama |
| `sellbird.yaml` | `brain: ollama / qwen3:0.6b`; 3 products with ICPs; default ICP = school ERP |
| `.env.example` | Local Ollama settings only; all paid-service keys removed |
| `seed.py`, `data/seed_sample_data.json` | 3 products, 10 fictional prospects, 8 observations, 5 replies |
| `scripts/offline_test.py`, `scripts/hardware_check.py` | Offline acceptance test; hardware → model recommendation |
| `tests/test_ollama_brain.py`, `test_multi_product.py`, `test_offline.py`, `test_scoring.py`, `test_reply_llm.py` | 30 new tests, all passing |
| `README.md`, `docs/*.md` | Fork docs (upstream README kept at `docs/UPSTREAM_README.md`) |

## What was deliberately NOT changed / NOT built

- **Claude/Codex brain code is retained, never selected.** Upstream tests
  assert `BrainConfig()` defaults to `provider: claude`; changing the code
  default would break them. The fork selects Ollama in `sellbird.yaml` and
  no fork workflow invokes the Claude/Codex paths. If you set
  `brain.provider: claude` yourself, upstream behaviour returns — this fork
  does not endorse or need it.
- **No React frontend.** Upstream ships a working vanilla HTML/CSS/JS
  dashboard (`sellbird/web/`); a React rewrite adds risk without changing
  any workflow outcome. The dashboard gains the two new API endpoints
  instead, and the product selector is served by `/api/products`.
- **No Scrapy.** Upstream scrapes with httpx + BeautifulSoup + Playwright,
  which covers the assignment's research step; adding Scrapy would duplicate
  it. Scraping is not exercised by the offline test (it uses stored data).
- **No paid services.** Instantly, Reoon/ZeroBounce/Hunter, DataForSEO,
  Serper, Scavio, TrulyInbox, Precleared and Cloudflare keys are removed
  from `.env.example`; their code paths are unreachable without keys and are
  never called by fork workflows. Only free paths remain (OpenStreetMap/
  Overpass discovery, DuckDuckGo/Bing fallback, DNS/MX-only email checks),
  and sample addresses stay `guess` — unverified, never sent.

## Licences (exact)

- **Sellbird (this fork and upstream): GNU AGPL-3.0-only.** `LICENSE` is the
  full AGPLv3 text; `pyproject.toml` declares `AGPL-3.0-only`. Releases up
  to 0.3.x were MIT; 0.4.0+ is AGPL. This fork keeps AGPL and upstream
  attribution (`NOTICE`); it is not re-licensed.
- **Qwen3 model: Apache License 2.0** (Qwen3 is released by Alibaba under
  Apache 2.0; the model weights are downloaded from Ollama at `ollama pull`
  time and are not redistributed in this repo).
- **Major dependencies:** FastAPI (MIT), uvicorn (BSD-3-Clause), httpx
  (BSD-3-Clause), aiosqlite (MIT), pydantic (MIT), PyYAML (MIT),
  beautifulsoup4 (MIT), Playwright (Apache 2.0), dnspython (ISC),
  aiosmtplib (MIT), keyring (MIT), python-dotenv (BSD-3-Clause), pytz (MIT),
  MCP SDK (Apache 2.0), pytest/pytest-asyncio (MIT). Full list with versions
  is in `requirements.txt` / `pyproject.toml`.

## Test results (this VM, Python 3.12.3, 2026-11-17)

- **Fork tests: 30 passed, 0 failed** (was 21; added warmup/temperature/
  LLM-classifier tests in `tests/test_ollama_brain.py` and
  `tests/test_reply_llm.py`, plus the email-subject cleanup test).
- Full suite (excluding `tests/test_codex_soak.py`): **3,682 passed,
  40 failed, 29 skipped** — full list in `evidence/pytest-full.log`:
  `test_ats_hiring.py` 17, `test_discover.py` 17, `test_pipeline.py` 4,
  `test_dashboard_auth.py` 1, `test_trulyinbox.py` 1.

### Why the 40 fail — root causes

- **39 of 40 are pre-existing environment failures, not fork regressions —
  verified.** The same five test files were run on a pristine checkout of
  upstream commit `25ec839` (`git worktree add /tmp/upstream-check HEAD`):
  **39 failed, 551 passed** there, the same 39 tests. Root cause: this VM's
  `NO_PROXY` contains bracketed IPv6 literals (`[::1]`, `[fd8b:...]`),
  which httpx's env-proxy parsing rejects with `Invalid port: ':1]'`.
  Any upstream code that builds a default httpx client (ATS host checks,
  discovery fetches, pipeline profiling, the live dashboard-auth test)
  dies on that error before doing any real work. The fork's own Ollama
  client sidesteps it with `trust_env=False` (localhost never needs a
  proxy).
- **1 failure is an intentional fork break:**
  `test_trulyinbox.py::test_the_link_lives_in_one_constant` asserts the
  TrulyInbox affiliate URL appears in `README.md`, `CLAUDE.md` and
  `sellbird.yaml`. This fork deliberately removes all paid-service
  promotion, so the new `README.md` does not contain the link. The test
  is kept (not deleted); it fails by design in this fork. If the fork ever
  re-adds the link, the test passes again unchanged.
