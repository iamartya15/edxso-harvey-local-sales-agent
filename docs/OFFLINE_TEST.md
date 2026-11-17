# Offline test

## What it is

`scripts/offline_test.py` runs all 8 workflows against locally stored
sample data (`data/seed_sample_data.json`) and writes evidence to
`evidence/offline-test-<timestamp>.md` and `.json`.

**Offline guarantee:** the script makes **no external HTTP call**. Without
`--use-ollama` it uses only the labelled deterministic templates. With
`--use-ollama` it may call **only** `http://localhost:11434` (the local
Ollama server). Either way, the evidence file states the source of every
result (`ollama-local` vs `deterministic-template`), so template output is
never mistaken for model output.

## Run it

```bash
# Templates only (works with no Ollama at all)
python scripts/offline_test.py
# -> Workflows run: 8/8 | reply classification: 5/5 correct

# With real local inference (needs ollama serve + a pulled model)
python scripts/offline_test.py --use-ollama
```

Exit code 0 means all 8 workflows produced a result; non-zero otherwise.

## What is checked

1. All 8 workflows run on the first product's seeded company/prospect.
2. Per-product scoring for **all 3 products** (same company scores
   differently per product — the multi-product proof).
3. Reply classification accuracy against the 5 labelled sample replies
   (expected 5/5).

## Manual offline procedure (for the demo video)

1. Start Ollama and pull the model **before** going offline:
   `ollama serve` + `ollama pull qwen3:0.6b` (check `ollama list`).
2. Disconnect Wi-Fi / unplug Ethernet. (On this VM: the test itself makes
   no external calls, so this step is demonstrative — the point is that
   nothing in the run needs the network.)
3. Run: `python scripts/offline_test.py --use-ollama`
4. Show the evidence file: every workflow result lists
   `source: ollama-local`, `model: qwen3:0.6b`, and the local host.
5. Re-run without the flag to show the labelled template fallback:
   `python scripts/offline_test.py` — results say
   `source: deterministic-template`.
6. Screenshot/record the terminal + the evidence `.md` file.

## Latest evidence

- `evidence/offline-test-20261117-115858.md` — **with real local inference**
  (`--use-ollama`, qwen3:0.6b, 5m17s): 8/8 workflows, rules 5/5, LLM 2/5.
- `evidence/offline-test-20261117-115935.md` — templates only, 8/8, 5/5.
- With models installed, re-run with `--use-ollama` (it pre-warms first):
  the evidence file then records `warmup`, `ollama_used: true`,
  `model: qwen3:0.6b`, per-workflow `source: ollama-local`, and both the
  rule-based and LLM reply-classification accuracies
  (`reply_classification_llm_accuracy`).
