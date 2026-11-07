"""Rewrite Twin-2K-500 persona summaries (games removed) as first-person accounts, with one fixed prompt.

  uv run python -m hotcold.make_twin_narratives --n 40

Output: data/derived/twin_narratives.yaml (model, prompt and one text per pid), used by --persona twin-narrative.
"""

from __future__ import annotations

import argparse
import asyncio

import yaml
from langchain_core.messages import HumanMessage

from .llm import LangChainModel
from .run import load_dotenv
from .sources import DERIVED, twin_sample, twin_summary

PROMPT = """Below is real information about a person who completed a long survey: demographics, personality and other psychological scores (with percentiles relative to a US sample), cognitive scores, economic attitudes, and their own written answers about who they are and want to be.

Rewrite it as this person describing themselves in their own words, in the first person, as in a long interview about their life (about 300 words).
Rules:
- Use only what the information says or directly implies. Do not invent names, places, jobs, events, family members or hobbies.
- Translate scores into plain-language tendencies, keeping their strength (e.g. 3rd percentile agreeableness: "I can be critical and I don't go out of my way to please people"; 90th percentile: "I'm warm and easy to get along with"). Average scores can be described as average or left out.
- Never mention scores, percentiles, tests, questionnaires or the survey.
- Keep the person's own written sentences about themselves close to how they wrote them.
- Write only the first-person text.

INFORMATION:
{summary}"""

MODEL = "deepinfra:deepseek-ai/DeepSeek-V4-Flash-0731"


async def main(n: int):
    load_dotenv()
    chat = LangChainModel(MODEL, max_tokens=4000).chat
    pids = twin_sample(n)
    sem = asyncio.Semaphore(8)

    async def one(pid):
        async with sem:
            r = await chat.ainvoke([HumanMessage(PROMPT.format(summary=twin_summary(pid)))])
            text = r.content if isinstance(r.content, str) else "".join(b.get("text", "") for b in r.content if isinstance(b, dict))
            return pid, text.strip()

    out = dict(await asyncio.gather(*(one(p) for p in pids)))
    DERIVED.mkdir(parents=True, exist_ok=True)
    doc = {"model": MODEL, "prompt": PROMPT, "source": "Twin-2K-500 persona_summary, economic games removed",
           "narratives": {int(k): v for k, v in out.items()}}
    (DERIVED / "twin_narratives.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110))
    print(f"{len(out)} narratives -> {DERIVED / 'twin_narratives.yaml'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    asyncio.run(main(ap.parse_args().n))
