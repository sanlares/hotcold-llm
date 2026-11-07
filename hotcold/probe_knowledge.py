"""Does a model already know the paper? One out-of-character question per model (no Persona, new conversation).

  uv run python -m hotcold.probe_knowledge --out runs/<batch>/knowledge_probe.csv     # 8 requests, a few cents

The in-character question at the end of the experiment ("have you seen this study?") is answered by the Persona,
so it measures at most that the agent recognises the type of game. This asks the model itself. A "no" does not
prove it was never trained on the paper; a correct summary of its results would show it was.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

import pandas as pd

from .batch import FINAL_MODELS
from .llm import LangChainModel, cost_usd
from .run import load_dotenv

SYSTEM = "Answer as yourself, an AI model. This is a question about your own knowledge, not a role-play."
QUESTION = (
    "Do you know the paper \"Hot-cold reciprocation gaps\" by Ghidoni, Suetens and Yang, published in Experimental "
    "Economics? If you know it, summarise its main result in two sentences; if you do not, say so and do not guess.\n\n"
    "Then, whether or not you know it: in its Baseline experiment, UK students played as second movers in a "
    "one-shot trust game repeated for 20 rounds with different partners. If the first mover trusts (IN), the second "
    "mover chooses LEFT (both earn 35) or RIGHT (she earns 50, the first mover 12). In 'Hot' she decides after seeing "
    "that she was trusted; in 'Cold' she decides in advance, conditional on being trusted. What percentage of second "
    "movers do you think chose LEFT in Hot, and in Cold?"
)
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["knows_paper", "summary", "predicted_left_hot", "predicted_left_cold"],
          "properties": {
              "knows_paper": {"type": "string", "enum": ["Yes", "No", "Not sure"], "description": "Do you know the paper?"},
              "summary": {"type": "string", "description": "Two-sentence summary of its main result, or 'I do not know it'."},
              "predicted_left_hot": {"type": "integer", "description": "Predicted % choosing LEFT in Hot (0-100)."},
              "predicted_left_cold": {"type": "integer", "description": "Predicted % choosing LEFT in Cold (0-100)."}}}


async def probe(models: list[str]) -> pd.DataFrame:
    async def one(m):
        try:
            ans, meta = await LangChainModel(m).respond(SYSTEM, [{"role": "user", "content": QUESTION}], SCHEMA)
        except Exception as e:  # one provider failing (e.g. no credit) must not lose the other answers
            return {"model": m, "knows_paper": None, "error": f"{type(e).__name__}: {e}"[:300]}
        return {"model": m, **(ans or {"knows_paper": None}), "model_version": meta.get("model_version"),
                "cost_usd": round(cost_usd(m, meta.get("usage", {})), 5), "raw": None if ans else meta.get("text")}
    return pd.DataFrame(await asyncio.gather(*(one(m) for m in models)))


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="final")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    models = FINAL_MODELS if a.models == "final" else a.models.split(",")
    df = asyncio.run(probe(models))
    df.insert(0, "asked", time.strftime("%Y-%m-%d"))
    out = a.out or Path(__file__).resolve().parents[1] / "runs" / f"knowledge_probe_{time.strftime('%Y%m%d-%H%M%S')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(df.reindex(columns=["model", "knows_paper", "predicted_left_hot", "predicted_left_cold", "summary", "error"]).to_string())
    print(f"-> {out}")


if __name__ == "__main__":
    main()
