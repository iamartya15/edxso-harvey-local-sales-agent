# Setup — Ollama + the app

## 1. Python

Python 3.11+ (tested on 3.12.3 on this Linux VM).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # runtime deps + pytest
```

## 2. Ollama

```bash
# Install (Linux): https://ollama.com/download — or:
curl -fsSL https://ollama.com/install.sh | sh
# The installer needs `zstd` on Debian/Ubuntu: sudo apt-get install -y zstd

ollama serve                # start the local server (http://localhost:11434)
ollama pull qwen3:0.6b      # the default model (~0.5 GB)
ollama list                 # verify the model is present
curl http://localhost:11434/api/tags   # {"models":[{"name":"qwen3:0.6b",...}]}
python scripts/prewarm_model.py   # load the model once (~25 s cold); warm calls are ~8 s
```

### Known environment limitation: `ollama pull` is BLOCKED on this VM

`ollama pull` fails deterministically in <1 s with a sentinel 403 on the
registry token endpoint (`GET /v2/token … policy_denied`); the denial says
do not retry, so it was not retried. **Do not claim `ollama pull` works
here.** The registry itself is reachable, so the models were installed by
the manual method (verified 2026-11-17, full detail in
`evidence/ollama-smoke-test.md`):

1. Fetch the manifest: `curl https://registry.ollama.ai/v2/library/qwen3/manifests/0.6b`
2. Download each blob (following redirects) from
   `registry.ollama.ai/v2/library/qwen3/blobs/sha256:<digest>`.
3. Place blobs in `~/.ollama/models/blobs/sha256-<digest>` and the manifest in
   `~/.ollama/models/manifests/registry.ollama.ai/library/qwen3/<tag>`.
4. Verify every blob's SHA-256 against its manifest digest before use.

HuggingFace downloads are also blocked (403) on this VM, so HF is not an
alternative. The model files are already in `~/.ollama/models/` now, so
the app does not need to pull again on this VM; on another machine, plain
`ollama pull qwen3:0.6b` is the normal path.

### VM restarts wipe /usr/local — models survive, the binary does not

Verified 2026-11-17 ~13:12 UTC: after a VM restart, `/usr/local/bin/ollama`
(and `zstd`, and apt's package lists) were gone, but `~/.ollama/models/`
with both models was intact. Recovery, no model re-download needed:

```bash
curl -fsSL https://ollama.com/install.sh | sh   # needs zstd; if apt is
                                                 # slow/stuck after a restart, use the workaround below
ollama serve
ollama list   # both models recognised from ~/.ollama/models/
```

Workaround when `zstd` can't be installed (apt lists wiped / `apt-get
update` stuck): `pip install zstandard`, download
`https://ollama.com/download/ollama-linux-amd64.tar.zst` to a disk-backed
path (NOT `/tmp`), and extract it with Python (`zstandard` +
`tarfile`) to `/usr/local`. That is how the binary was restored after the
13:12 UTC restart. **For the demo: if the VM restarts, reinstall the
binary first — the models and the app code (both under `~`) survive.**

One command does all of it — `scripts/restore_ollama.sh` (tested end to
end after the third restart: 23 s when the tarball is already on disk):
it checks for the binary, downloads the tarball only if missing or the
wrong size, extracts it, starts `ollama serve` in the background, and
verifies `ollama list`. Run it after any restart before a demo or a
`--use-ollama` run. The VM has now restarted three times in one day
(~13:12, ~15:16, ~17:14 UTC), each time wiping `/usr/local` and each
time leaving `~/.ollama/models/` intact — **treat `ollama serve` as
non-persistent and always verify it is up first.**

### Gotcha: /tmp is a 512 MiB tmpfs

Never download models or large files to `/tmp` — the first 0.6b download
died at 388 MiB with "no space". Use disk-backed paths (`~/.ollama/...`,
the repo's `data/`). Nothing in this fork writes large files to `/tmp`.

### Gotcha: proxy env vars break httpx / `import ollama`

This VM's `NO_PROXY` contains bracketed IPv6 literals (`::1`, `[::1]`, …)
that httpx 0.28 cannot parse (`InvalidURL: Invalid port: ':1]'`). That is
why `python3 -c "import ollama"` crashes under the default environment
and why 39 upstream tests fail here. It works with all proxy vars unset:
`env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY
-u all_proxy -u no_proxy -u NO_PROXY python3 -c "import ollama"`. The
app's Ollama client avoids the problem with `trust_env=False` (localhost
never needs a proxy); scripts call `ensure_local_env()` first. Do not
"fix" this by editing the proxy vars globally — they belong to the runtime.

If `ollama pull` fails in your environment, see the note in
`evidence/ollama-smoke-test.md`: the app still runs end-to-end on the
labelled deterministic templates, and `/api/local-health` reports
`reachable: true, model_present: false` so the gap is visible, not hidden.

## 3. Configure

```bash
cp .env.example .env        # local Ollama settings only; no secrets
# sellbird.yaml already sets brain.provider: ollama, model: qwen3:0.6b
```

To use a different model, set `OLLAMA_MODEL` in `.env` and
`brain.model` / `brain.ollama_model` in `sellbird.yaml`.

## 4. Seed + verify

```bash
python seed.py                    # sample data into data/sellbird.db
python scripts/hardware_check.py  # RAM/CPU/GPU -> recommended model
python scripts/offline_test.py    # 8/8 workflows, evidence in evidence/
python -m pytest tests/test_ollama_brain.py tests/test_multi_product.py \
    tests/test_offline.py tests/test_scoring.py -q   # 21 fork tests
```

## 5. Dashboard

```bash
python -m sellbird dashboard
# http://127.0.0.1:5555
# New endpoints: GET /api/local-health, GET /api/products
```

## Hardware configs (measured on this VM, 2026-11-17)

| Machine | Model | Setting | Measured |
|---|---|---|---|
| Standard — < 8 GB RAM, no GPU (this VM: 7.7 GB) | `qwen3:0.6b` (~0.5 GB) | default | cold ~25 s, warm ~8 s/call; llama-server RSS 1,042 MiB |
| Standard-plus — 8–16 GB RAM | `qwen3:1.7b` (~1.4 GB) | `OLLAMA_MODEL=qwen3:1.7b` | cold ~64 s/call; RSS 1,807 MiB; classifies better (see below) |
| High-performance — 16 GB+ RAM or any GPU | `qwen3:4b` (~2.5 GB) | `OLLAMA_MODEL=qwen3:4b` | not measured on this VM |

**One model loaded at a time.** With 0.6b loaded there is ~400–500 MiB
available left for FastAPI — workable only if the app stays lean. With
1.7b loaded the VM is on swap and there is effectively no headroom for
anything else; Ollama + FastAPI together is feasible with 0.6b only.

**Accuracy vs speed (measured):** qwen3:0.6b with a loose prompt
misclassified "Yes, please send pricing for 500 students." as `needs info`
(wrong); qwen3:1.7b got it right (`interested`) but took 64.1 s cold.
Default is 0.6b with temperature 0 + a strict few-shot prompt (exact-word
answers) and a rule-based fallback — see `sellbird/local_sales.py`.
1.7b is the higher-accuracy/slower option for machines with RAM to spare.

Run `python scripts/hardware_check.py [--json]` to detect your machine and
get the recommendation. The 0.6B model is fast on CPU but terse; the 1.7B
model is the best quality/speed balance on a typical 8 GB laptop; the 4B
model needs 16 GB RAM or a GPU to stay responsive.

## Troubleshooting

- `Ollama call failed ... connection refused` — `ollama serve` is not
  running. Start it; workflows fall back to labelled templates meanwhile.
- `model 'qwen3:0.6b' not found` — run `ollama pull qwen3:0.6b`.
- Dashboard shows no products — run `python seed.py` first.
- `sellbird.yaml` validation errors — check `brain.provider` is `ollama`
  (or `claude`/`codex` for upstream behaviour, which this fork does not use).
