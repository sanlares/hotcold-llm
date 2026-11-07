"""manifest.json: everything needed to say exactly what produced a run.

LLM answers cannot be reproduced word for word (providers sample, and may update a model behind the same name),
so replicability here means: the same code, data, prompt and settings, plus an archive of every conversation.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

from .llm import MODELS
from .materials import QSF
from .personas import DATASET, RAW
from .subject import DEBRIEF_SCREEN, FORMAT_RETRIES, SYSTEM_TEMPLATE

HERE = Path(__file__).resolve().parents[1]
LIBRARIES = ["langchain", "langchain-core", "langchain-anthropic", "langchain-openai", "anthropic", "openai",
             "pandas", "pyarrow"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted((HERE / "hotcold").glob("*")):
        if p.suffix in (".py", ".yaml"):
            h.update(p.name.encode() + p.read_bytes())
    return h.hexdigest()


def git_state() -> dict:
    def git(*args):
        return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True).stdout.strip()
    try:
        commit = git("rev-parse", "HEAD")
    except FileNotFoundError:
        return {}
    return {"commit": commit or None, "dirty": bool(git("status", "--porcelain", "--", "hotcold", "tests")) if commit else None}


def data_files(cfg: dict) -> dict:
    files = {"qsf": QSF[cfg.get("experiment", "baseline")], "raw_export": RAW[cfg.get("experiment", "baseline")],
             "dataset": DATASET}
    if cfg.get("persona") == "nemotron":
        from .sources import NEMO_FILE
        files["nemotron"] = NEMO_FILE
    return {k: {"path": str(v.relative_to(HERE.parent)) if v.is_relative_to(HERE.parent) else str(v),
                "sha256": sha256(v)} for k, v in files.items()}


def write_manifest(outdir: Path, cfg: dict) -> dict:
    model = cfg.get("model")
    m = {
        "written": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": git_state(),
        "code_sha256": code_hash(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "libraries": {lib: _version(lib) for lib in LIBRARIES},
        "uv_lock_sha256": sha256(HERE / "uv.lock") if (HERE / "uv.lock").exists() else None,
        "data": data_files(cfg),
        "model": model,
        "model_settings": MODELS.get(model, {}).get(cfg.get("thinking", "off")) if model in MODELS else None,
        "prices_usd_per_mtok_in_out_cache": MODELS.get(model, {}).get("price"),
        "temperature": "provider default (not set)",
        "format_retries": FORMAT_RETRIES,
        "system_template": SYSTEM_TEMPLATE,
        "debrief_screen": DEBRIEF_SCREEN,
    }
    # keep earlier manifests of a resumed run: one entry per session that wrote to this folder
    path = outdir / "manifest.json"
    history = json.loads(path.read_text()) if path.exists() else []
    history = history if isinstance(history, list) else [history]
    path.write_text(json.dumps(history + [m], indent=2, default=str))
    return m


def _version(lib: str) -> str | None:
    try:
        return metadata.version(lib)
    except metadata.PackageNotFoundError:
        return None
