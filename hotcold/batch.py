"""Run several models x Personas at once, with limits per provider shared by every run.

  uv run python -m hotcold.batch --models final --personas demographic,nemotron --n-per-treatment 5
  uv run python -m hotcold.batch --models final --personas demographic,nemotron --n-per-treatment 0 --yes --max-cost 30
  uv run python -m hotcold.batch --resume runs/<batch>              # finish an interrupted batch
  uv run python -m hotcold.batch ... --dry-run                       # scripted models, no API calls

Each model x Persona combination is an ordinary run folder (see run.py) inside runs/<batch>/. While it runs,
runs/<batch>/status.json shows, for every combination, how many agents are done, excluded, failed, and the cost.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path

from .llm import MODELS
from .run import (FINAL_SOURCES, PILOT_SOURCES, RUNS, Budget, drop_errors, file_log, finish_run, load_dotenv,
                  model_factory, prepare_run, run_agents, select_personas, setup_logging)

log = logging.getLogger("hotcold")

# The 8 models of the final design (registered with the tutor, 2026-11-07).
FINAL_MODELS = [
    "deepinfra:deepseek-ai/DeepSeek-V4-Flash-0731",
    "deepinfra:meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "deepinfra:google/gemma-4-31B-it-turbo",
    "deepinfra:openai/gpt-oss-120b",
    "deepinfra:Qwen/Qwen3-235B-A22B-Instruct-2507",
    "deepinfra:Qwen/Qwen3.8-Flash",
    "anthropic:claude-haiku-5-5",
    "openai:gpt-5-nano",
]
DEFAULT_LIMITS = {"deepinfra": 64, "anthropic": 16, "openai": 16}  # agents in progress at once, per provider


def short(model: str) -> str:
    return model.split("/")[-1].split(":")[-1]


def parse_limits(text: str) -> dict:
    limits = dict(DEFAULT_LIMITS)
    for part in filter(None, text.split(",")):
        k, v = part.split("=")
        limits[k.strip()] = int(v)
    return limits


async def run_batch(combos: list[dict], limits: dict, budget: Budget, root: Path) -> list[dict]:
    sems = {prov: asyncio.Semaphore(n) for prov, n in limits.items()}
    states = {}

    def write_status():
        rows = [{"run": c["name"], **{k: v for k, v in asdict(states[c["name"]]).items() if k != "started"}}
                for c in combos if c["name"] in states]
        (root / "status.json").write_text(json.dumps({"updated": time.strftime("%H:%M:%S"), "spent_usd":
                                                      round(budget.spent, 4), "runs": rows}, indent=2))

    async def one(c):
        prov = "scripted" if c["cfg"]["dry_run"] else c["cfg"]["model"].split(":")[0]
        sem = sems.setdefault(prov, asyncio.Semaphore(limits.get(prov, 16)))
        st = await run_agents(c["personas"], c["make_model"], c["cfg"]["model"], c["outdir"], sem, budget,
                              c["cfg"]["explain"], c["name"], on_start=lambda s: states.__setitem__(c["name"], s))
        return c, st

    async def heartbeat():
        while True:
            await asyncio.sleep(15)
            write_status()

    hb = asyncio.create_task(heartbeat())
    out = []
    for fut in asyncio.as_completed([one(c) for c in combos]):
        c, st = await fut
        text = finish_run(c["outdir"], c["personas"], st)
        log.info("finished %s\n%s", c["name"], text)
        out.append({"run": c["name"], "stopped": st.stopped, "cost": round(st.cost, 4)})
        write_status()
    hb.cancel()
    return out


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="final", help="'final' (the 8 models of the design) or a comma list of MODELS keys")
    ap.add_argument("--personas", default="demographic,nemotron")
    ap.add_argument("--n-per-treatment", type=int, default=5, help="0 = all 396 participants")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--persona-seed", type=int, default=0)
    ap.add_argument("--thinking", choices=["off", "on"], default="off")
    ap.add_argument("--limits", default="", help="agents at once per provider, e.g. deepinfra=32,anthropic=16")
    ap.add_argument("--max-cost", type=float, default=None, help="USD for the whole batch; no new agent starts beyond it")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--resume", type=Path, help="finish this batch folder")
    ap.add_argument("--retry-errors", action="store_true", help="with --resume: redo agents with technical errors")
    ap.add_argument("--tag", default="", help="label added to the batch folder name")
    a = ap.parse_args()
    setup_logging()

    if a.resume:
        root = a.resume
        spec = json.loads((root / "batch.json").read_text())
    else:
        models = FINAL_MODELS if a.models == "final" else [m.strip() for m in a.models.split(",")]
        unknown = [m for m in models if m not in MODELS]
        if unknown:
            raise SystemExit(f"unknown models: {unknown}")
        personas = [p.strip() for p in a.personas.split(",")]
        bad = [p for p in personas if p not in FINAL_SOURCES + PILOT_SOURCES]
        if bad:
            raise SystemExit(f"unknown Personas: {bad}")
        spec = {"models": models, "personas": personas, "n_per_treatment": a.n_per_treatment, "seed": a.seed,
                "persona_seed": a.persona_seed, "thinking": a.thinking, "dry_run": a.dry_run,
                "limits": parse_limits(a.limits), "max_cost": a.max_cost}
        n = 396 if not a.n_per_treatment else 4 * a.n_per_treatment
        if not a.dry_run and n * len(models) * len(personas) > 400 and not a.yes:
            raise SystemExit(f"{n * len(models) * len(personas)} agent sessions: re-run with --yes to confirm.")
        root = RUNS / (time.strftime("%Y%m%d-%H%M%S") + "_batch" + (f"_{a.tag}" if a.tag else "")
                       + ("_dryrun" if a.dry_run else ""))
        root.mkdir(parents=True)
        (root / "batch.json").write_text(json.dumps(spec, indent=2))
    file_log_root = logging.FileHandler(root / "batch.log")
    file_log_root.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(file_log_root)

    combos = []
    for persona in spec["personas"]:
        people = select_personas(persona, spec["n_per_treatment"], spec["seed"], spec["persona_seed"])
        for model in spec["models"]:
            name = f"{short(model) if not spec['dry_run'] else 'scripted-' + short(model)}_{persona}"
            outdir = root / name
            cfg = {"experiment": "baseline", "model": "scripted" if spec["dry_run"] else model, "persona": persona,
                   "n_per_treatment": spec["n_per_treatment"], "seed": spec["seed"],
                   "persona_seed": spec["persona_seed"], "thinking": spec["thinking"], "explain": False,
                   "dry_run": spec["dry_run"], "n_agents": len(people), "batch": root.name}
            prepare_run(outdir, cfg, people)
            file_log(outdir, name)
            if a.resume and a.retry_errors:
                log.info("%s: %d agents with technical errors moved aside to run again", name, drop_errors(outdir))
            combos.append({"name": name, "cfg": cfg, "personas": people, "outdir": outdir,
                           "make_model": model_factory(model, spec["thinking"], spec["dry_run"])})
    log.info("batch %s: %d runs, %d agent sessions, limits %s", root.name, len(combos),
             sum(len(c["personas"]) for c in combos), spec["limits"])
    out = asyncio.run(run_batch(combos, spec["limits"], Budget(spec["max_cost"]), root))
    stopped = [r for r in out if r["stopped"]]
    log.info("batch done: $%.3f%s", sum(r["cost"] for r in out),
             "" if not stopped else f" -- {len(stopped)} runs stopped early: resume with --resume {root}")


if __name__ == "__main__":
    main()
