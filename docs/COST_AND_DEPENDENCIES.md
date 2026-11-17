# Cost & dependencies — zero-cost proof

## The claim

Running this fork costs **Rs.0 / $0**: no paid LLM API, no subscription,
no paid third-party service, no per-call or per-seat charge. The only
"costs" are the machine you already own, electricity, and your time.

## What costs money upstream — and what this fork does instead

| Upstream cost | Fork status |
|---|---|
| Claude Pro/Max subscription (Brain via `claude` CLI) | **Removed by config.** `brain.provider: ollama`; no fork workflow calls the Claude path. Code retained only for upstream test compatibility. |
| ChatGPT plan (Brain via Codex CLI) | **Removed by config**, same as above. |
| OpenAI / Anthropic / Gemini API keys | **None anywhere.** Grep the tree (see below) — no such keys, no such imports in fork code. |
| Instantly (cold-email platform, paid plan for API) | Key removed from `.env.example`; never called by fork workflows. |
| Reoon / ZeroBounce / Hunter (email verification) | Keys removed; without a verifier, addresses stay `guess` and are **never sent**. |
| DataForSEO / Serper / Scavio (discovery data) | Keys removed; discovery falls back to free OpenStreetMap/Overpass and DuckDuckGo/Bing scraping. |
| TrulyInbox (warmup), Precleared (compliance), Cloudflare Browser Rendering | Keys removed; warmup/compliance checks that need them are skipped, not faked. |
| Sellbird hosted version (sellbird.ai) | Not used; everything runs locally. |

## How to verify (do this yourself)

```bash
# 1. No paid-LLM imports or keys in the fork's code
grep -rn "openai\|anthropic\|gemini" sellbird/ollama_brain.py sellbird/local_sales.py \
    seed.py scripts/ --include="*.py" -i
# -> no matches (see evidence/grep-paid-apis.txt)

grep -rn "sk-\|ANTHROPIC_API_KEY\|OPENAI_API_KEY\|GEMINI_API_KEY" \
    .env.example sellbird.yaml sellbird/ --include="*.py" --include="*.yaml" --include="*.example"
# -> no matches

# 2. No external network during a run: the offline test makes zero external calls
python scripts/offline_test.py
# Evidence file states: "External HTTP calls: none"

# 3. Live check: watch what the app actually contacts while the dashboard runs
# (Linux) sudo ss -tnp | grep ollama   # only 127.0.0.1:11434 (localhost)
# Every inference is logged with host + model in data/inference_log.jsonl:
cat data/inference_log.jsonl | python -m json.tool
# -> "host": "http://localhost:11434", "model": "qwen3:0.6b", "source": "ollama-local"

# 4. Dashboard proof: GET /api/local-health returns "paid_api_calls": 0
curl http://127.0.0.1:5555/api/local-health
```

## Limitations of the zero-cost claim

- **Ollama model download is free but needs network access to the Ollama
  registry.** In this VM the registry token endpoint returned 403
  (policy-denied), so no model could be pulled here; see
  `evidence/ollama-smoke-test.md`. The claim "zero cost" is about money,
  not about network reachability.
- **Free tiers are not used as a crutch.** Where upstream offered a free
  tier (e.g. Hunter 25 searches/month), this fork does not call it at all
  in the demo path — the demo uses stored sample data, so no quota is
  consumed and no account is needed.
- **Sending email is still gated.** Even with a free SMTP/Gmail account,
  cold email has deliverability and legal (consent) costs that money can't
  remove. This fork never sends to the sample addresses.
- **Hardware is the real cost.** A 0.6B model runs on 7.7 GB RAM; a 4B model
  wants 16 GB or a GPU. See `docs/SETUP.md`.
