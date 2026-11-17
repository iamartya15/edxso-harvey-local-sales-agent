"""Hardware check — recommend an Ollama model size for this machine.

Usage: python scripts/hardware_check.py [--json]

Reads RAM / CPU / GPU (Linux: /proc/meminfo, lscpu, nvidia-smi when present)
and prints the recommended model tier:

- < 8 GB RAM  -> qwen3:0.6b (standard config, ~0.5 GB)
- 8-16 GB RAM -> qwen3:1.7b (~1.4 GB)
- 16 GB+ or a GPU -> qwen3:4b (~2.5 GB) or larger

Exits 0. Makes no network calls.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess


def total_ram_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return 0.0


def cpu_info() -> dict:
    info: dict = {"count": os.cpu_count() or 0, "model": platform.processor() or "unknown"}
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    info["model"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return info


def gpu_info() -> list[str]:
    gpus: list[str] = []
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            gpus = [line.strip() for line in out.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.SubprocessError):
            pass
    return gpus


def recommend(ram_gb: float, gpus: list[str]) -> dict:
    if gpus:
        return {"tier": "high-performance", "model": "qwen3:4b",
                "why": f"GPU detected ({gpus[0]}); 4B model fits comfortably."}
    if ram_gb >= 16:
        return {"tier": "high-performance", "model": "qwen3:4b",
                "why": f"{ram_gb:.1f} GB RAM; 4B model (~2.5 GB) leaves room for the app."}
    if ram_gb >= 8:
        return {"tier": "standard-plus", "model": "qwen3:1.7b",
                "why": f"{ram_gb:.1f} GB RAM; 1.7B model (~1.4 GB) is the sweet spot."}
    return {"tier": "standard", "model": "qwen3:0.6b",
            "why": f"{ram_gb:.1f} GB RAM; 0.6B model (~0.5 GB) is the only safe choice."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    ram = total_ram_gb()
    gpus = gpu_info()
    report = {
        "ram_gb": round(ram, 1),
        "cpu": cpu_info(),
        "gpus": gpus,
        "recommendation": recommend(ram, gpus),
        "ollama_host": os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        "configs": {
            "standard (qwen3:0.6b)": "RAM < 8 GB — default in sellbird.yaml",
            "standard-plus (qwen3:1.7b)": "RAM 8-16 GB — set brain.model / OLLAMA_MODEL=qwen3:1.7b",
            "high-performance (qwen3:4b)": "RAM 16 GB+ or GPU — set OLLAMA_MODEL=qwen3:4b",
        },
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        rec = report["recommendation"]
        print(f"RAM: {report['ram_gb']} GB | CPUs: {report['cpu']['count']} ({report['cpu']['model']})")
        print(f"GPU: {gpus[0] if gpus else 'none detected'}")
        print(f"Recommended: {rec['model']} ({rec['tier']}) — {rec['why']}")
        print("Run: ollama pull " + rec["model"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
