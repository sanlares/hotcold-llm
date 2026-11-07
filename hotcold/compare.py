"""Tables comparing Persona sources across models (pilot runs of 20 agents, same IN/OUT sequences).

  uv run python -m hotcold.compare            # prints markdown tables, writes runs/compare_sources.md
"""

from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd

from .run import RUNS

SOURCES = ["basic", "rich", "prism", "nemotron", "twin-summary", "twin-narrative"]
MODELS = {
    "claude-haiku-5-5": "Haiku", "DeepSeek-V4-Flash-0731": "DeepSeek V4 Flash",
    "Qwen3-235B-A22B-Instruct-2507": "Qwen3 235B", "Qwen3.8-Flash": "Qwen 3.8 Flash",
    "gemma-4-31B-it-turbo": "Gemma 4", "gpt-oss-120b": "gpt-oss-120b",
    "Llama-4-Scout-17B-16E-Instruct": "Llama 4 Scout",
}


def latest(model: str, source: str) -> Path | None:
    suffix = "" if source == "basic" else f"-{source}"
    hits = sorted(glob.glob(str(RUNS / f"*_{model}{suffix}_n20")))
    return Path(hits[-1]) if hits else None


def hotcold_stats(path: Path) -> dict:
    p, s = pd.read_csv(path / "panel.csv"), pd.read_csv(path / "subjects.csv")
    x = p[(p.p1trust == 1) & p.reci.notna()] if len(p) else p
    per = x.groupby("agent_id").reci.mean() if len(x) else pd.Series(dtype=float)
    pct = lambda v: round(100 * v) if v == v else None
    return {
        "Hot": pct(x[x.hot == 1].reci.mean()) if len(x) else None,
        "Cold": pct(x[x.hot == 0].reci.mean()) if len(x) else None,
        "a veces": int(((per > 0) & (per < 1)).sum()), "nunca": int((per == 0).sum()), "siempre": int((per == 1).sum()),
        "completos": int(s.completed.sum()), "costo": round(float(s.cost_usd.sum()), 3),
    }


def hotcold_table() -> pd.DataFrame:
    rows = []
    for m, label in MODELS.items():
        for src in SOURCES:
            path = latest(m, src)
            if path:
                rows.append({"modelo": label, "fuente": src, **hotcold_stats(path)})
    return pd.DataFrame(rows)


def human_row() -> dict:
    path = latest("claude-haiku-5-5", "basic")
    p = pd.read_csv(path / "panel.csv")
    x = p[(p.p1trust == 1) & p.human_reci.notna()]
    per = x.groupby("agent_id").human_reci.mean()
    return {"Hot": round(100 * x[x.hot == 1].human_reci.mean()), "Cold": round(100 * x[x.hot == 0].human_reci.mean()),
            "a veces": int(((per > 0) & (per < 1)).sum()), "nunca": int((per == 0).sum()), "siempre": int((per == 1).sum())}


def trust_table() -> pd.DataFrame:
    rows = []
    for m, label in MODELS.items():
        for fmt in ["twin-demographic", "twin-summary", "twin-narrative", "twin-qa"]:
            f = RUNS / f"twin_trust_{fmt}_{m}" / "answers.csv"
            if not f.exists():
                continue
            d = pd.read_csv(f)
            ok = d.dropna(subset=["agent_return_pct", "agent_send_pct"])
            r = {"modelo": label, "formato": fmt, "n": len(ok)}
            for k, name in (("send_pct", "envía"), ("return_pct", "devuelve")):
                h, g = ok[f"human_{k}"], ok[f"agent_{k}"]
                r[f"{name} humano"] = round(h.mean())
                r[f"{name} agente"] = round(g.mean())
                r[f"{name} corr"] = round(h.corr(g), 2) if g.std() > 0 else None
                r[f"{name} dif abs"] = round((h - g).abs().mean())
            rows.append(r)
    return pd.DataFrame(rows)


def main():
    out = ["# Comparación de fuentes de Persona (pilotos de 20 agentes)\n"]
    hc = hotcold_table()
    if len(hc):
        out += ["## Hot–cold: % de veces que devuelven la confianza\n", "Humanos (mismos 20): " + str(human_row()) + "\n",
                hc.to_markdown(index=False), ""]
    tt = trust_table()
    if len(tt):
        out += ["## Validación con el juego de confianza de Twin-2K-500\n", tt.to_markdown(index=False), ""]
    text = "\n".join(out)
    (RUNS / "compare_sources.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
