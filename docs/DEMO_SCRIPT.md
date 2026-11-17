# Demo script — 5–10 min screen recording

Record at 1080p, terminal + browser side by side where useful. Speak the
narration; the timings are a guide, not a script to read verbatim.

## 0. Setup shot (0:00–0:45)
- Terminal: `ollama list` → shows `qwen3:0.6b` (and `qwen3:1.7b`). `curl localhost:11434/api/tags`.
- `python scripts/prewarm_model.py` → warmup in ~25 s cold; say "the model
  is loaded once now, so every call after this is warm (~8 s)."
- Say: "Everything runs on this machine — Ollama, Qwen3 0.6B, no cloud API."

## 1. Start the app (0:45–1:30)
- `python seed.py` → "products=3, companies=10, prospects=10…"
- `python -m sellbird dashboard` → open http://127.0.0.1:5555.
- Browser: `GET /api/local-health` → `reachable: true, model: qwen3:0.6b,
  paid_api_calls: 0`. Then `/api/products` → the 3 products.

## 2. Business profile + ICP (1:30–3:00)
- Terminal: run the workflows (or show `scripts/offline_test.py --use-ollama`
  output). Point at the business-profile result for Sunrise Public School.
- Say what the profile is and what it is not: "generated locally from stored
  facts — the model invents nothing, and the log says which model wrote it."
- Show the ICP for VidyaSetu School ERP: K-12 schools, Principal/Director,
  Uttar Pradesh; then switch product to ClassBook and show its different ICP.

## 3. Prospects, signals, problem statements (3:00–5:00)
- Show the 10 sample prospects (`.test` domains — say clearly these are
  fictional sample data, not real schools).
- Highlight Little Scholars Academy: hiring an Admission Counsellor → buying
  signal → problem statement linking the hiring signal to the school ERP.
- Show the per-product scores: the same school scores high for the ERP and
  low for the coaching suite.

## 4. Emails + reply classification (5:00–7:00)
- Show a generated email: subject line, under 75 words, grounded in the
  problem statement. Say: "Draft only — sample addresses are unverified
  guesses, so nothing is sent."
- Show the 5 sample replies and their classifications (interested / question /
  opt-out / not interested) — 5/5 against the labels.

## 5. Local inference logs (7:00–8:00)
- `cat data/inference_log.jsonl` — every entry: `host: localhost:11434`,
  `model: qwen3:0.6b`, `source: ollama-local`, timestamp, latency.
- Say: "This is the audit trail. If it were a cloud model, the host would
  say so — there is no cloud call to hide."

## 6. Offline repeat (8:00–9:30)
- Disconnect Wi-Fi on camera. Run `python scripts/offline_test.py --use-ollama`
  again → 8/8 workflows, evidence file written.
- Open `evidence/offline-test-<timestamp>.md` and read the verdict line.
- Reconnect, stop recording.

## 7. Close (9:30–10:00)
- One line: "Local multi-product sales agent: 3 products, 8 workflows,
  zero paid APIs, and every run is provably offline."
- Show the repo: `README.md`, `docs/`, `evidence/`.

## If Ollama has no model yet (fallback — not the case on this VM any more)
If `ollama pull` is blocked on the recording machine, record the same flow
with `python scripts/offline_test.py` (templates) and say so on camera:
"the model pull is blocked on this network, so this run uses the labelled
deterministic templates — the workflows, scoring and classification are
identical; only the text generator differs." Do not present template output
as model output. On this VM the models are already installed (manual
manifest/blob method, see `docs/SETUP.md`), so the normal recording uses
`--use-ollama` after `scripts/prewarm_model.py`.

## 0.6b classification note (say it once, honestly)
The 0.6b model is weak at classification: with a loose prompt it once
called "Yes, please send pricing for 500 students" `needs info`. The demo
uses temperature 0 + a strict few-shot prompt with exact-word answers, and
the rule-based classifier as fallback — show both the LLM and rule intents
in the evidence file when you show reply classification, and say the
1.7b model classifies better but is too slow/heavy for this machine.
