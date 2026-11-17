"""Pre-warm the local Ollama model so later calls are warm, not cold.

Usage:
    python scripts/prewarm_model.py [--model qwen3:0.6b]

Verified timings on this VM: qwen3:0.6b cold ~25 s, warm ~8 s per short
call; qwen3:1.7b cold ~64 s. Run this once at startup (or before a demo)
and keep exactly one model loaded — 0.6b RSS ~1,042 MiB, 1.7b ~1,807 MiB
on a 7.7 GiB VM, so 1.7b leaves effectively no headroom for FastAPI.

Exits 0 when the model answers, 1 otherwise. Makes no external HTTP call
(localhost only). Never writes anything to /tmp (512 MiB tmpfs).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sellbird.ollama_brain import OllamaBrain, ensure_local_env  # noqa: E402

ensure_local_env()


async def main_async(model: str | None) -> int:
    brain = OllamaBrain(model=model)
    health = await brain.health_check()
    print(f"Ollama health: {health}")
    if not health["reachable"]:
        print("Ollama server is not reachable on", brain.host)
        return 1
    if not health.get("model_present"):
        print(f"Model {brain.model} is not pulled on this host.")
        print("On this VM `ollama pull` is blocked (sentinel 403 on the registry")
        print("token endpoint) — see docs/SETUP.md for the manual manifest/blob")
        print("workaround, or run `ollama pull` from an approved context.")
        return 1
    warmed = await brain.warmup()
    print(f"Warmup: {warmed}")
    return 0 if warmed["warmed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None, help="e.g. qwen3:0.6b (default) or qwen3:1.7b")
    args = parser.parse_args()
    return asyncio.run(main_async(args.model))


if __name__ == "__main__":
    raise SystemExit(main())
