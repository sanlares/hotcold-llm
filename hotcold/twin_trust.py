"""Validation: does a Persona built from a real Twin-2K-500 participant reproduce that person's trust game?

The agent answers the participant's own trust game with the original wording (QID117 as sender; QID118-122 as
receiver for $5..$1 sent, i.e. $15..$3 received). The Persona never contains these games (sources.py removes them).

  uv run python -m hotcold.twin_trust --format twin-summary --model deepinfra:meta-llama/Llama-4-Scout-17B-16E-Instruct

Output: runs/twin_trust_<format>_<model>/answers.csv and summary.txt
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time

import pandas as pd

from .llm import MODELS, LangChainModel, cost_usd
from .run import RUNS, load_dotenv
from .sources import EXT, twin_sample, twin_text

RECEIVER = ["QID118", "QID119", "QID120", "QID121", "QID122"]  # $5, $4, $3, $2, $1 sent
SYSTEM_TAIL = "\n\nYou are now answering a survey. Answer each question as yourself."


def catalog() -> dict:
    return {q["QuestionID"]: q for q in json.loads((EXT / "twin/question_catalog.json").read_text())}


def human_answers() -> pd.DataFrame:
    return pd.read_csv(EXT / "twin/wave1_3_response_label.csv", usecols=["pid", "QID117", *RECEIVER]).set_index("pid")


def sent(option: str) -> int:
    return int(re.search(r"send \$(\d+)", option).group(1))


def _enum(options):
    return {"type": "string", "enum": list(options)}


def _obj(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


async def play(model, pid: int, fmt: str, cat: dict):
    system = twin_text(pid, fmt) + SYSTEM_TAIL
    q1 = cat["QID117"]
    opts = "\n".join(f"- {o}" for o in q1["Options"])
    messages = [{"role": "user", "content": f"{q1['QuestionText']}\n\n{opts}\n\n(answer field: answer)"}]
    usage, out = {}, {"pid": pid}
    a1, m1 = await model.respond(system, messages, _obj({"answer": _enum(q1["Options"])}))
    _add(usage, m1)
    if a1 is None:
        return {**out, "error": "sender"}, usage
    out["QID117"] = a1["answer"]
    messages.append({"role": "assistant", "content": m1["text"]})

    parts, props = [], {}
    for i, qid in enumerate(RECEIVER):
        q = cat[qid]
        text = q["QuestionText"] if i == 0 else q["QuestionText"].strip()
        key = f"r{5 - i}"
        parts.append(f"{text}\n" + "\n".join(f"- {o}" for o in q["Options"]) + f"\n(answer field: {key})")
        props[key] = _enum(q["Options"])
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    a2, m2 = await model.respond(system, messages, _obj(props))
    _add(usage, m2)
    if a2 is None:
        return {**out, "error": "receiver"}, usage
    for i, qid in enumerate(RECEIVER):
        out[qid] = a2[f"r{5 - i}"]
    return out, usage


def _add(usage, meta):
    for k, v in meta.get("usage", {}).items():
        usage[k] = usage.get(k, 0) + (v or 0)


def scores(row) -> dict:
    """Percent sent as sender; mean share returned as receiver (sent back / amount received)."""
    s = {"send_pct": 100 * sent(row["QID117"]) / 5}
    s["return_pct"] = 100 * sum(sent(row[q]) / (3 * (5 - i)) for i, q in enumerate(RECEIVER)) / len(RECEIVER)
    return s


async def main(fmt: str, model_name: str, n: int, concurrency: int):
    load_dotenv()
    cat = catalog()
    pids = twin_sample(n)
    sem = asyncio.Semaphore(concurrency)
    model = LangChainModel(model_name)

    async def one(pid):
        async with sem:
            return await play(model, pid, fmt, cat)

    t0 = time.time()
    res = await asyncio.gather(*(one(p) for p in pids))
    usage = {}
    for _, u in res:
        for k, v in u.items():
            usage[k] = usage.get(k, 0) + v
    agent = pd.DataFrame([r for r, _ in res]).set_index("pid")
    human = human_answers().loc[pids]
    rows = []
    for pid in pids:
        a = agent.loc[pid]
        row = {"pid": pid, **{f"human_{k}": v for k, v in scores(human.loc[pid]).items()}}
        if "error" not in a or pd.isna(a.get("error")):
            row.update({f"agent_{k}": v for k, v in scores(a).items()})
        rows.append(row)
    df = pd.DataFrame(rows)
    tag = model_name.split("/")[-1].split(":")[-1]
    out = RUNS / f"twin_trust_{fmt}_{tag}"
    out.mkdir(parents=True, exist_ok=True)
    agent.reset_index().merge(df, on="pid").to_csv(out / "answers.csv", index=False)
    ok = df.dropna()
    lines = [f"format={fmt} model={model_name} n={len(pids)} valid={len(ok)} cost=${cost_usd(model_name, usage):.4f} "
             f"time={time.time() - t0:.0f}s"]
    for k in ("send_pct", "return_pct"):
        h, g = ok[f"human_{k}"], ok[f"agent_{k}"]
        corr = h.corr(g) if g.std() > 0 and h.std() > 0 else float("nan")
        lines.append(f"{k}: human mean {h.mean():.1f} sd {h.std():.1f} | agent mean {g.mean():.1f} sd {g.std():.1f} | "
                     f"corr {corr:.2f} | mean abs diff {(h - g).abs().mean():.1f}")
    text = "\n".join(lines)
    (out / "summary.txt").write_text(text)
    print(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="twin-summary", choices=["twin-demographic", "twin-summary", "twin-narrative", "twin-qa"])
    ap.add_argument("--model", default="anthropic:claude-haiku-5-5", choices=list(MODELS))
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=8)
    a = ap.parse_args()
    asyncio.run(main(a.format, a.model, a.n, a.concurrency))
