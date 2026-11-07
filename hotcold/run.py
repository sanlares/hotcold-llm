"""Run a set of agents through the experiment and save everything under runs/<run_id>/.

  uv run python -m hotcold.run --n-per-treatment 5 --model anthropic:claude-haiku-5-5
  uv run python -m hotcold.run --n-per-treatment 5 --dry-run           # scripted model, no API calls
  uv run python -m hotcold.run --resume runs/<run_id>                  # finish an interrupted run
  uv run python -m hotcold.run --resume runs/<run_id> --retry-errors   # also redo agents with technical errors
(several models x Personas at once, with shared limits per provider: hotcold.batch)

Outputs (one folder per run):
  config.json     run parameters
  manifest.json   versions of code, data and libraries (replicability)
  personas.csv    agent_id <-> real_id and the Persona text each agent received
  results.jsonl   one line per finished agent: its result and the full conversation
  panel.csv       one row per agent x round, same variables as hotcold_dataset + the paired human's choice
  subjects.csv    one row per agent: quiz, questionnaire, debrief, checks, exclusions, tokens, cost
  calls.jsonl     one line per request sent: latency, tokens, model version, technical retries, failed text
  run.log         progress, warnings and errors
  summary.txt     first look at the results
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from .llm import API_KEYS, MODELS, FatalAPIError, LangChainModel, ScriptedModel, cost_usd
from .materials import load
from .personas import (DATASET, DATASET_LABEL, Persona, add_rich, build_personas, demographic_personas,
                       to_frame)
from .subject import Subject, parse_age

RUNS = Path(__file__).resolve().parents[1] / "runs"
TREATS = {("Hot", "28%"): "Hot-Low", ("Hot", "69%"): "Hot-High", ("Cold", "28%"): "Cold-Low", ("Cold", "69%"): "Cold-High"}
FINAL_SOURCES = ["demographic", "nemotron"]  # the two Personas of the final design
PILOT_SOURCES = ["basic", "rich", "prism", "twin-summary", "twin-narrative", "twin-qa", "twin-demographic"]
MAX_CONSECUTIVE_ERRORS = 10
PROGRESS_EVERY = 10

log = logging.getLogger("hotcold")


# --- which agents -------------------------------------------------------------------------------------------
def sample(personas, n_per_treatment: int | None, seed: int):
    df = to_frame(personas)
    df["treat"] = [TREATS[(t, c)] for t, c in zip(df.treatment, df.crate)]
    if n_per_treatment:
        df = df.groupby("treat", group_keys=False).sample(n=n_per_treatment, random_state=seed)
    keep = set(df.agent_id)
    return [p for p in personas if p.agent_id in keep]


def select_personas(source: str, n_per_treatment: int | None, seed: int = 1, persona_seed: int = 0,
                    experiment: str = "baseline") -> list[Persona]:
    """The agents of a run. Final design: any sample of the real participants (0/None = all 396). Pilot sources
    (rich, prism, twin-*) only exist for the fixed 20 pilot agents."""
    people = build_personas(experiment, persona_seed)
    if source == "rich":
        return add_rich(people)
    if source in PILOT_SOURCES[2:]:
        from . import sources
        return sources.build(source, sample(people, 5, 1))
    people = sample(people, n_per_treatment or None, seed)
    if source == "demographic":
        return demographic_personas(people)
    if source == "nemotron":
        from . import sources
        return sources.nemotron_personas(people, persona_seed)
    if source == "basic":
        return people
    raise ValueError(source)


# --- running ------------------------------------------------------------------------------------------------
@dataclass
class Budget:
    """Spending shared by every run of a batch; no new agent starts once the limit is reached."""
    limit: float | None = None
    spent: float = 0.0

    @property
    def exceeded(self) -> bool:
        return self.limit is not None and self.spent >= self.limit


@dataclass
class RunState:
    total: int
    done: int = 0
    completed: int = 0
    quiz_excluded: int = 0
    errors: int = 0
    consecutive_errors: int = 0
    format_retries: int = 0
    cost: float = 0.0
    stopped: str = ""  # why the run stopped early ("" = it did not)
    started: float = field(default_factory=time.time)

    def line(self, name: str) -> str:
        el = time.time() - self.started
        eta = el / self.done * (self.total - self.done) if self.done else 0
        return (f"{name}: {self.done}/{self.total} | completed {self.completed} | quiz-excluded {self.quiz_excluded}"
                f" | errors {self.errors} | retries {self.format_retries} | ${self.cost:.3f} | eta {eta / 60:.0f} min")


def done_ids(outdir: Path) -> set[str]:
    path = outdir / "results.jsonl"
    return {json.loads(x)["agent_id"] for x in path.open()} if path.exists() else set()


def drop_errors(outdir: Path) -> int:
    """For --retry-errors: move agents flagged with a technical error out of results.jsonl (kept aside)."""
    path = outdir / "results.jsonl"
    if not path.exists():
        return 0
    lines = path.read_text().splitlines()
    bad = [x for x in lines if json.loads(x)["drop_stage"] == 9]
    with (outdir / "results_retried_errors.jsonl").open("a") as f:
        f.writelines(x + "\n" for x in bad)
    path.write_text("".join(x + "\n" for x in lines if json.loads(x)["drop_stage"] != 9))
    return len(bad)


async def run_agents(personas: list[Persona], make_model: Callable, model_name: str, outdir: Path,
                     sem: asyncio.Semaphore, budget: Budget | None = None, explain: bool = False,
                     name: str = "", on_start: Callable[[RunState], None] | None = None) -> RunState:
    """Run every agent not yet in outdir/results.jsonl. Each finished agent is written at once, so an interrupted
    run loses nothing and can be resumed. One agent's failure never stops the others."""
    budget = budget or Budget()
    name = name or outdir.name
    rlog = logging.getLogger(f"hotcold.{name}")
    outdir.mkdir(parents=True, exist_ok=True)
    already = done_ids(outdir)
    todo = [p for p in personas if p.agent_id not in already]
    st = RunState(total=len(todo))
    if on_start:
        on_start(st)
    if already:
        rlog.info("%s: resuming, %d agents already done, %d to go", name, len(already), len(todo))
    results_f = (outdir / "results.jsonl").open("a")
    calls_f = (outdir / "calls.jsonl").open("a")

    def log_call(rec: dict) -> None:
        calls_f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}) + "\n")

    async def one(p: Persona) -> None:
        async with sem:
            if st.stopped or budget.exceeded:
                if budget.exceeded and not st.stopped:
                    st.stopped = f"spending limit reached (${budget.spent:.2f})"
                    rlog.warning("%s: %s; remaining agents not started (resume later)", name, st.stopped)
                return
            s = Subject(p, load(p.experiment), make_model(), explain, log_call=log_call)
            try:
                res = await s.run()
            except FatalAPIError as e:
                if not st.stopped:
                    st.stopped = f"fatal API error: {e}"
                    rlog.error("%s: %s -- run stopped; fix it and resume", name, e)
                return
            cost = cost_usd(model_name, res.usage)
            budget.spent += cost
            results_f.write(json.dumps({**asdict(res), "cost_usd": cost, "model": model_name,
                                        "system": s.system, "messages": s.messages}) + "\n")
            results_f.flush()
            calls_f.flush()
            st.done += 1
            st.cost += cost
            st.format_retries += res.format_retries
            st.completed += res.completed
            st.quiz_excluded += res.drop_stage == 2
            if res.drop_stage == 9:
                st.errors += 1
                st.consecutive_errors += 1
                rlog.warning("%s: %s technical error: %s", name, p.agent_id, res.error[:300])
                if st.consecutive_errors >= MAX_CONSECUTIVE_ERRORS and not st.stopped:
                    st.stopped = f"{MAX_CONSECUTIVE_ERRORS} technical errors in a row"
                    rlog.error("%s: %s -- run paused to avoid wasting money; check run.log, then resume", name, st.stopped)
            else:
                st.consecutive_errors = 0
            if st.done % PROGRESS_EVERY == 0 or st.done == st.total:
                rlog.info(st.line(name))

    try:
        await asyncio.gather(*(one(p) for p in todo))
    finally:
        results_f.close()
        calls_f.close()
    return st


# --- saving -------------------------------------------------------------------------------------------------
def load_results(outdir: Path) -> list[dict]:
    path = outdir / "results.jsonl"
    return [json.loads(x) for x in path.open()] if path.exists() else []


def save(outdir: Path, personas: list[Persona], experiment: str = "baseline"):
    """panel.csv and subjects.csv from results.jsonl. Odd answers are kept as given and flagged in check columns."""
    by_id = {p.agent_id: p for p in personas}
    human = pd.read_csv(DATASET, usecols=["experiment", "id", "round", "reci"])
    human = human[human.experiment == DATASET_LABEL[experiment]].rename(columns={"id": "real_id", "reci": "human_reci"})

    rows, subj = [], []
    for r in load_results(outdir):
        treat = TREATS[(r["treatment"], r["crate"])]
        p = by_id[r["agent_id"]]
        common = {"agent_id": r["agent_id"], "real_id": r["real_id"], "treat": treat, "group": r["group"],
                  "model": r["model"], "persona": p.source}
        for x in r["rounds"]:
            rows.append({**common, "experiment": experiment, "hot": int(r["treatment"] == "Hot"),
                         "phigh": int(r["crate"] == "69%"), **x})
        q = r["questionnaire"]
        age = parse_age(q["age"]) if "age" in q else None
        subj.append({
            **common, "completed": r["completed"], "drop_stage": r["drop_stage"], "error": r["error"],
            "quiz_attempts": r["quiz_attempts"], "calls": r["calls"], "requests": r["requests"],
            "format_retries": r["format_retries"], "seconds": r["seconds"],
            "model_versions": "; ".join(r["model_versions"]),
            "real_age": p.age, "real_gender": p.gender, "real_education": p.education,
            "persona_ref": p.source_ref, "match_age_diff": p.match_age_diff, "match_education": p.match_education,
            **{f"q_{k}": v for k, v in q.items()},
            **{f"d_{k}": v for k, v in r["debrief"].items()},
            # checks: the model's behaviour, recorded, never corrected
            "chk_age_number": age,
            "chk_age_plausible": None if not q else age is not None and 16 <= age <= 99,
            "chk_age_matches": None if not q else age == p.age,
            "chk_gender_matches": None if not q else q.get("gender") == p.gender,
            "chk_education_matches": None if not q else q.get("education") == p.education,
            **r["usage"], "cost_usd": round(r["cost_usd"], 5),
        })
    panel = pd.DataFrame(rows)
    if len(panel):
        panel = panel.merge(human[["real_id", "round", "human_reci"]], on=["real_id", "round"], how="left")
    panel.to_csv(outdir / "panel.csv", index=False)
    subjects = pd.DataFrame(subj)
    subjects.to_csv(outdir / "subjects.csv", index=False)
    return panel, subjects


def summary(panel: pd.DataFrame, subjects: pd.DataFrame) -> str:
    if not len(subjects):
        return "no agents finished"
    lines = [f"agents: {len(subjects)}, completed: {int(subjects.completed.sum())}, "
             f"quiz-excluded: {int((subjects.drop_stage == 2).sum())}, technical errors: {int((subjects.drop_stage == 9).sum())}, "
             f"format retries: {int(subjects.format_retries.sum())}, cost: ${subjects.cost_usd.sum():.4f}"]
    if len(panel):
        dec = panel[panel.reci.notna()]  # as in the paper: Hot = rounds with IN; Cold = every round
        t = dec.groupby("treat").agg(llm_reci=("reci", "mean"), human_reci=("human_reci", "mean"), n=("reci", "size"))
        lines.append("Reciprocation rate, all decisions (same persons, same sequences; tables: hotcold.analysis):")
        lines.append(t.round(3).to_string())
    return "\n".join(lines)


# --- setup helpers ----------------------------------------------------------------------------------------------
def load_dotenv(path: Path = Path(__file__).resolve().parents[1] / ".env") -> None:
    """Read KEY=value lines from hotcold_llm/.env into the environment (existing variables win)."""
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def model_factory(model: str, thinking: str = "off", dry_run: bool = False) -> Callable:
    if dry_run:
        return lambda: ScriptedModel("random")
    key = API_KEYS[model.split(":")[0]]
    if not os.environ.get(key):
        raise SystemExit(f"{key} is not set (export it, or put {key}=... in hotcold_llm/.env).")
    return lambda: LangChainModel(model, thinking)


def setup_logging(console: bool = True) -> None:
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    if console:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        log.addHandler(h)


def file_log(outdir: Path, name: str) -> logging.Handler:
    h = logging.FileHandler(outdir / "run.log")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger(f"hotcold.{name}").addHandler(h)
    return h


def prepare_run(outdir: Path, cfg: dict, personas: list[Persona]) -> None:
    from .manifest import write_manifest

    outdir.mkdir(parents=True, exist_ok=True)
    if not (outdir / "config.json").exists():
        (outdir / "config.json").write_text(json.dumps(cfg, indent=2))
        to_frame(personas).to_csv(outdir / "personas.csv", index=False)
    write_manifest(outdir, cfg)


def finish_run(outdir: Path, personas: list[Persona], st: RunState) -> str:
    panel, subjects = save(outdir, personas)
    text = summary(panel, subjects)
    if st.stopped:
        text += f"\nSTOPPED EARLY: {st.stopped} (resume with --resume {outdir})"
    (outdir / "summary.txt").write_text(text + f"\noutput: {outdir}\n")
    return text


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", default="baseline")
    ap.add_argument("--n-per-treatment", type=int, default=5, help="0 = all participants")
    ap.add_argument("--model", default="anthropic:claude-haiku-5-5", choices=list(MODELS))
    ap.add_argument("--thinking", choices=["off", "on"], default="off")
    ap.add_argument("--seed", type=int, default=1, help="sampling seed")
    ap.add_argument("--persona-seed", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--persona", default="demographic", choices=FINAL_SOURCES + PILOT_SOURCES,
                    help="Persona source; final design: demographic, nemotron. The rest are pilot-only (20 agents)")
    ap.add_argument("--explain", action="store_true", help="diagnostic: agent also gives a one-sentence reason per choice")
    ap.add_argument("--dry-run", action="store_true", help="scripted model, no API calls")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation for runs above 40 agents")
    ap.add_argument("--max-cost", type=float, default=None, help="stop starting agents beyond this many USD")
    ap.add_argument("--resume", type=Path, help="finish this run folder (its config.json wins over other options)")
    ap.add_argument("--retry-errors", action="store_true", help="with --resume: redo agents with technical errors")
    a = ap.parse_args()
    setup_logging()

    if a.resume:
        cfg = json.loads((a.resume / "config.json").read_text())
        outdir = a.resume
        if a.retry_errors:
            log.info("moved %d agents with technical errors aside, to run again", drop_errors(outdir))
    else:
        tag = ("scripted" if a.dry_run else a.model.split("/")[-1].split(":")[-1]) + \
              ("" if a.dry_run or a.thinking == "off" else "-thinking") + ("-explain" if a.explain else "") + f"-{a.persona}"
        cfg = {**{k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()},
               "model": "scripted" if a.dry_run else a.model}
        outdir = None
    personas = select_personas(cfg["persona"], cfg["n_per_treatment"], cfg["seed"], cfg["persona_seed"], cfg["experiment"])
    if not cfg["dry_run"] and len(personas) > 40 and not (a.yes or a.resume):
        raise SystemExit(f"{len(personas)} agents: re-run with --yes to confirm a run of this size.")
    if outdir is None:
        outdir = RUNS / (time.strftime("%Y%m%d-%H%M%S") + f"_{tag}_n{len(personas)}")
    cfg["n_agents"] = len(personas)
    prepare_run(outdir, cfg, personas)
    file_log(outdir, outdir.name)
    make_model = model_factory(cfg["model"], cfg["thinking"], cfg["dry_run"])
    st = asyncio.run(run_agents(personas, make_model, cfg["model"], outdir, asyncio.Semaphore(a.concurrency),
                                Budget(a.max_cost), cfg["explain"]))
    print(finish_run(outdir, personas, st))


if __name__ == "__main__":
    main()
