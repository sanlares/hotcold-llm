"""Pre-specified analysis (docs/plan_de_analisis.md): agents vs the same humans vs theory.

  uv run python -m hotcold.analysis --validate              # reproduce the paper's Table 2 with the human data
  uv run python -m hotcold.analysis runs/<batch>            # all tables + figure -> runs/<batch>/analysis/

Definitions follow the paper (Table 2, tab2.do):
  - a reciprocation decision is any non-missing `reci`: in Hot, the rounds where the first mover chose IN; in Cold,
    every round (the choice is made conditional on IN, before knowing the first mover's choice);
  - windows: round 1, rounds 19-20, rounds 1-20;
  - linear probability model reci ~ hot + phigh (+ hot x phigh) + age + female + i.edu, standard errors clustered
    by participant (rounds 19-20 and 1-20). For agents, the controls are the paired real person's.
Theory: a second mover who only maximises her payoff never reciprocates (0%) in Hot nor in Cold (paper, Sec. 2);
the surprise model predicts Hot >= Cold, with a larger gap in Low than in High.
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .personas import DATASET

WINDOWS = {"round 1": (1, 1), "rounds 19-20": (19, 20), "rounds 1-20": (1, 20)}
CELLS = ["Hot-Low", "Cold-Low", "Hot-High", "Cold-High"]
EDU = {"High school or below": "High school or below", "Bachelor student": "Bachelor", "Master student": "Master",
       "PhD student or above": "PhD or above", "Other": "Other"}  # Qualtrics answer -> dataset label
PAPER_TABLE2 = {  # coefficient of Hot (and Hot x High), paper Table 2
    ("round 1", False): 0.005, ("rounds 19-20", False): 0.103, ("rounds 1-20", False): 0.056,
    ("round 1", True): 0.010, ("rounds 19-20", True): 0.177, ("rounds 1-20", True): 0.065,
}
PAPER_N = {"round 1": 395, "rounds 19-20": 579, "rounds 1-20": 5815}
PAPER_SE = {  # standard error of Hot, paper Table 2
    ("round 1", False): 0.050, ("rounds 19-20", False): 0.049, ("rounds 1-20", False): 0.036,
    ("round 1", True): 0.071, ("rounds 19-20", True): 0.081, ("rounds 1-20", True): 0.048,
}


# --- data ---------------------------------------------------------------------------------------------------
def humans() -> pd.DataFrame:
    d = pd.read_csv(DATASET)
    d = d[(d.finished == 1) & (d.experiment == "Baseline experiment")].copy()
    d["female"] = d.female.map({"Female": 1, "Other": 0})  # the csv stores Stata value labels
    d["hot"], d["phigh"] = (d.hot == "Hot").astype(int), (d.phigh == "High").astype(int)
    d["treat"] = np.where(d.hot == 1, "Hot", "Cold") + "-" + np.where(d.phigh == 1, "High", "Low")
    d = d.rename(columns={"id": "real_id"})
    d["agent_id"] = d.real_id
    d["source"] = "humans"
    return d[["agent_id", "real_id", "round", "hot", "phigh", "treat", "p1trust", "reci", "age", "female", "edu", "source"]]


def load_runs(paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """panel and subjects of every run folder; agents get the paired real person's demographics as controls."""
    panels, subjects = [], []
    for p in paths:
        pan, sub = pd.read_csv(p / "panel.csv"), pd.read_csv(p / "subjects.csv")
        per = pd.read_csv(p / "personas.csv")[["agent_id", "age", "gender", "education"]]
        if not len(pan):
            continue
        # as the paper (finished==1): only agents that completed every original screen
        pan = pan[pan.agent_id.isin(sub.loc[sub.completed.astype(bool), "agent_id"])]
        pan = pan.merge(per, on="agent_id", how="left")
        pan["female"] = pan.gender.map({"Female": 1, "Male": 0, "Other": 0})
        pan["edu"] = pan.education.map(EDU)
        pan["source"] = pan.model.str.split("/").str[-1].str.split(":").str[-1] + " · " + pan.persona
        sub["source"] = sub.model.str.split("/").str[-1].str.split(":").str[-1] + " · " + sub.persona
        panels.append(pan)
        subjects.append(sub)
    return pd.concat(panels, ignore_index=True), pd.concat(subjects, ignore_index=True)


def decisions(panel: pd.DataFrame, window: str) -> pd.DataFrame:
    lo, hi = WINDOWS[window]
    return panel[panel.reci.notna() & panel["round"].between(lo, hi)]


# --- statistics -----------------------------------------------------------------------------------------------
def ols_cluster(df: pd.DataFrame, interaction: bool, cluster: bool) -> dict:
    """reci ~ hot + phigh [+ hot:phigh] + age + female + i.edu, as in tab2.do (Stata CR1 clustered SEs)."""
    d = df.dropna(subset=["reci", "hot", "phigh", "age", "female", "edu"])
    X = pd.DataFrame({"const": 1.0, "hot": d.hot.astype(float), "phigh": d.phigh.astype(float)})
    if interaction:
        X["hot_x_high"] = X.hot * X.phigh
    X["age"], X["female"] = d.age.astype(float), d.female.astype(float)
    edu = pd.get_dummies(d.edu, prefix="edu", dtype=float)
    X = pd.concat([X, edu.drop(columns=edu.columns[0])], axis=1)
    X = X.loc[:, X.std() > 0].assign(const=1.0) if len(X) else X  # a model may have no variation in a control
    y, Xv = d.reci.astype(float).values, X.values
    XtX_inv = np.linalg.pinv(Xv.T @ Xv)
    beta = XtX_inv @ Xv.T @ y
    e = y - Xv @ beta
    n, k = Xv.shape
    if cluster:
        g = d.agent_id.values
        meat = np.zeros((k, k))
        for gid in np.unique(g):
            s = Xv[g == gid].T @ e[g == gid]
            meat += np.outer(s, s)
        G = len(np.unique(g))
        V = XtX_inv @ meat @ XtX_inv * (G / (G - 1)) * ((n - 1) / (n - k))
    else:
        V = XtX_inv * (e @ e) / (n - k)
    se = np.sqrt(np.diag(V))
    out = {"n": n}
    for name in ("hot", "phigh", "hot_x_high"):
        if name in X.columns:
            i = list(X.columns).index(name)
            out[name], out[f"{name}_se"] = beta[i], se[i]
    return out


def _boot(d: pd.DataFrame, reps: int = 1000, seed: int = 0) -> np.ndarray:
    """Bootstrap draws of the share of reciprocation decisions, resampling agents (an agent's rounds stay together)."""
    g = d.groupby("agent_id").reci.agg(["sum", "count"])
    s, c = g["sum"].values, g["count"].values
    idx = np.random.default_rng(seed).integers(0, len(g), size=(reps, len(g)))
    return s[idx].sum(1) / c[idx].sum(1)


def bootstrap_rate(d: pd.DataFrame, reps: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """Share of reciprocation decisions with a 95% interval that resamples agents. For agents of one model the
    interval only reflects chance under this prompt and this model version (agents are not independent people)."""
    if not len(d):
        return (np.nan, np.nan, np.nan)
    draws = _boot(d, reps, seed)
    return d.reci.sum() / len(d), np.quantile(draws, 0.025), np.quantile(draws, 0.975)


MIN_AGENTS = 30  # pre-registered: a cell with fewer completed agents is shown but its gap is not interpreted


def rates_table(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for src, p in panel.groupby("source", sort=False):
        for w in WINDOWS:
            d = decisions(p, w)
            row = {"source": src, "window": w}
            for cell in CELLS:
                r, lo, hi = bootstrap_rate(d[d.treat == cell])
                row[cell] = f"{100 * r:.0f} [{100 * lo:.0f}–{100 * hi:.0f}]" if r == r else ""
            rows.append(row)
    return pd.DataFrame(rows)


def gap_table(panel: pd.DataFrame, window: str = "rounds 19-20") -> pd.DataFrame:
    """Hot - Cold gap in Low and High with 95% intervals, and the verdict on the paper's main result."""
    rows = []
    for src, p in panel.groupby("source", sort=False):
        d = decisions(p, window)
        cells = {c: d[d.treat == c] for c in CELLS}
        n = {c: cells[c].agent_id.nunique() for c in CELLS}
        row = {"source": src, "agents per cell (HL/CL/HH/CH)": "/".join(str(n[c]) for c in CELLS)}
        if min(n.values()) == 0:
            rows.append({**row, "verdict": "empty cell"})
            continue
        draws = {c: _boot(cells[c], seed=i) for i, c in enumerate(CELLS)}
        point = {c: cells[c].reci.mean() for c in CELLS}
        gaps = {}
        for lvl in ("Low", "High"):
            g, gd = point[f"Hot-{lvl}"] - point[f"Cold-{lvl}"], draws[f"Hot-{lvl}"] - draws[f"Cold-{lvl}"]
            gaps[lvl] = (g, np.quantile(gd, 0.025), np.quantile(gd, 0.975))
            row[f"gap {lvl} (pp)"] = f"{100 * g:+.0f} [{100 * gaps[lvl][1]:+.0f}, {100 * gaps[lvl][2]:+.0f}]"
        dd = (draws["Hot-Low"] - draws["Cold-Low"]) - (draws["Hot-High"] - draws["Cold-High"])
        row["gap Low − gap High (pp)"] = (f"{100 * (gaps['Low'][0] - gaps['High'][0]):+.0f} "
                                          f"[{100 * np.quantile(dd, 0.025):+.0f}, {100 * np.quantile(dd, 0.975):+.0f}]")
        lo, hi = gaps["Low"][1], gaps["Low"][2]
        if d.reci.nunique() == 1:
            verdict = f"no variation (always {'LEFT' if d.reci.iloc[0] == 1 else 'RIGHT'})"
        elif min(n.values()) < MIN_AGENTS:
            verdict = f"cell under {MIN_AGENTS} agents: not interpreted"
        elif lo > 0:
            verdict = "as in the paper: Hot > Cold in Low"
        elif hi < 0:
            verdict = "against the paper: Cold > Hot in Low"
        else:
            verdict = "cannot tell"
        rows.append({**row, "verdict": verdict})
    return pd.DataFrame(rows)


def regression_table(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for src, p in panel.groupby("source", sort=False):
        for w in WINDOWS:
            d = decisions(p, w)
            for inter in (False, True):
                if d.agent_id.nunique() < MIN_AGENTS or d.reci.nunique() < 2:
                    rows.append({"source": src, "window": w, "spec": "Hot×High" if inter else "Hot + High",
                                 "n": len(d), "Hot": "—", "Hot×High": "—"})
                    continue
                r = ols_cluster(d, inter, cluster=w != "round 1")
                rows.append({"source": src, "window": w, "spec": "Hot×High" if inter else "Hot + High", "n": r["n"],
                             "Hot": f"{r.get('hot', np.nan):.3f} ({r.get('hot_se', np.nan):.3f})",
                             "Hot×High": f"{r['hot_x_high']:.3f} ({r['hot_x_high_se']:.3f})" if inter and "hot_x_high" in r else ""})
    return pd.DataFrame(rows)


def types_table(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for src, p in panel.groupby("source", sort=False):
        per = p[p.reci.notna()].groupby("agent_id").reci.mean()
        rows.append({"source": src, "agents": len(per), "never %": round(100 * (per == 0).mean()),
                     "sometimes %": round(100 * ((per > 0) & (per < 1)).mean()), "always %": round(100 * (per == 1).mean())})
    return pd.DataFrame(rows)


def rounds_table(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel[panel.reci.notna()].copy()
    p["block"] = pd.cut(p["round"], [0, 5, 10, 15, 20], labels=["1-5", "6-10", "11-15", "16-20"])
    p["mode"] = np.where(p.hot == 1, "Hot", "Cold")
    t = p.groupby(["source", "mode", "block"], sort=False, observed=True).reci.mean().unstack("block")
    return (100 * t).round(0).reset_index()


def checks_table(subjects: pd.DataFrame, panel: pd.DataFrame, human_r2: float) -> pd.DataFrame:
    rows = []
    for src, s in subjects.groupby("source", sort=False):
        done = s[s.completed]
        r2 = demographics_r2(panel[panel.source == src])
        rows.append({
            "source": src, "agents": len(s), "completed": int(s.completed.sum()),
            "quiz-excluded": int((s.drop_stage == 2).sum()), "technical errors": int((s.drop_stage == 9).sum()),
            "format retries": int(s.format_retries.sum()), "quiz attempts (mean)": round(s.quiz_attempts.mean(), 2),
            "age plausible %": _pct(done.get("chk_age_plausible")), "age = Persona %": _pct(done.get("chk_age_matches")),
            "gender = Persona %": _pct(done.get("chk_gender_matches")),
            "education = Persona %": _pct(done.get("chk_education_matches")),
            "says it knows a similar study %": _pct(done.get("d_seen_before", pd.Series(dtype=str)).eq("Yes")),
            "debrief failed": int(s.get("debrief_error", pd.Series(dtype=str)).fillna("").astype(bool).sum()),
            f"R² demographics (humans {100 * human_r2:.1f}%)": f"{100 * r2:.1f}%",
            "model versions": "; ".join(sorted(set("; ".join(s.model_versions.dropna().astype(str)).split("; ")) - {""})),
            "cost USD": round(s.cost_usd.sum(), 3),
        })
    return pd.DataFrame(rows)


def exclusions_table(subjects: pd.DataFrame) -> pd.DataFrame:
    """Agents that entered / completed / were excluded, per treatment cell (humans: 0.6% failed the quiz)."""
    rows = []
    for (src, cell), s in subjects.groupby(["source", "treat"], sort=False):
        rows.append({"source": src, "cell": cell, "agents": len(s), "completed": int(s.completed.sum()),
                     "quiz-excluded": int((s.drop_stage == 2).sum()), "technical errors": int((s.drop_stage == 9).sum())})
    return pd.DataFrame(rows)


def persona_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Demographic vs Nemotron Persona for each model, on the participants that completed in both."""
    rows = []
    for model, p in panel.groupby("model", sort=False):
        arms = {a: g for a, g in p.groupby("persona")}
        if not {"demographic", "nemotron"} <= set(arms):
            continue
        both = set(arms["demographic"].real_id) & set(arms["nemotron"].real_id)
        row = {"model": model.split("/")[-1].split(":")[-1], "participants in both": len(both)}
        for a in ("demographic", "nemotron"):
            d = arms[a][arms[a].real_id.isin(both) & arms[a].reci.notna()]
            row[f"{a} %"] = round(100 * d.reci.mean()) if len(d) else None
        d = arms["demographic"][arms["demographic"].real_id.isin(both) & arms["demographic"].human_reci.notna()]
        row["paired humans %"] = round(100 * d.human_reci.mean()) if len(d) else None
        rows.append(row)
    return pd.DataFrame(rows)


def demographics_r2(panel: pd.DataFrame) -> float:
    """How much of the differences in reciprocation between agents age, gender and education explain (stereotypes)."""
    per = panel[panel.reci.notna()].groupby("agent_id").agg(reci=("reci", "mean"), age=("age", "first"),
                                                             female=("female", "first"), edu=("edu", "first")).dropna()
    if len(per) < 10 or per.reci.std() == 0:
        return 0.0
    X = pd.concat([pd.Series(1.0, index=per.index, name="c"), per[["age", "female"]].astype(float),
                   pd.get_dummies(per.edu, drop_first=True, dtype=float)], axis=1).values
    beta, *_ = np.linalg.lstsq(X, per.reci.values, rcond=None)
    return 1 - (per.reci.values - X @ beta).var() / per.reci.var(ddof=0)


def _pct(s) -> str:
    if s is None or not len(s.dropna()):
        return ""
    return f"{100 * s.dropna().astype(bool).mean():.0f}"


# --- figure -------------------------------------------------------------------------------------------------------
def figure(panel: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    srcs = list(dict.fromkeys(panel.source))
    fig, axes = plt.subplots(1, 2, figsize=(12, 0.45 * len(srcs) + 1.5), sharey=True)
    for ax, c in zip(axes, ("Low", "High")):
        d = decisions(panel, "rounds 19-20")
        for i, src in enumerate(srcs):
            for j, (mode, color) in enumerate((("Hot", "#c0392b"), ("Cold", "#2c7fb8"))):
                r, lo, hi = bootstrap_rate(d[(d.source == src) & (d.treat == f"{mode}-{c}")])
                if r == r:
                    y = i + (0.18 if j else -0.18)
                    ax.errorbar(100 * r, y, xerr=[[100 * (r - lo)], [100 * (hi - r)]], fmt="o", color=color,
                                label=mode if i == 0 else None, capsize=2)
        ax.axvline(0, color="grey", lw=0.8, ls=":")
        ax.set_title(f"Trust rate {c} — rounds 19–20")
        ax.set_xlabel("% reciprocate (95% interval)")
        ax.set_xlim(-3, 103)
    axes[0].set_yticks(range(len(srcs)), srcs)
    axes[0].invert_yaxis()
    axes[0].legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --- entry points -------------------------------------------------------------------------------------------------
def validate() -> list[str]:
    """Reproduce Table 2 of the paper from the human data: coefficient and standard error of Hot (3 decimals), N,
    and the two gaps quoted in the text."""
    h = humans()
    problems = []
    for (w, inter), target in PAPER_TABLE2.items():
        r = ols_cluster(decisions(h, w), inter, cluster=w != "round 1")
        if round(r["hot"], 3) != target:
            problems.append(f"{w}, {'Hot×High' if inter else 'Hot+High'}: Hot = {r['hot']:.3f}, paper {target}")
        if round(r["hot_se"], 3) != PAPER_SE[(w, inter)]:
            problems.append(f"{w}, {'Hot×High' if inter else 'Hot+High'}: SE = {r['hot_se']:.3f}, paper {PAPER_SE[(w, inter)]}")
        if r["n"] != PAPER_N[w]:
            problems.append(f"{w}: N = {r['n']}, paper {PAPER_N[w]}")
    # the gaps quoted in the text (17.73 pp in Low, 6.58 in High, rounds 19-20) are the interacted model's
    # Hot effect in Low and Hot + Hot×High in High, with controls
    r = ols_cluster(decisions(h, "rounds 19-20"), True, cluster=True)
    for c, got, target in (("Low", r["hot"], 17.73), ("High", r["hot"] + r["hot_x_high"], 6.58)):
        if abs(100 * got - target) > 0.011:  # rounding of the published figure
            problems.append(f"Hot-Cold gap {c}, rounds 19-20 = {100 * got:.2f} pp, paper {target}")
    return problems


def with_paired_humans(h: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """All 396 humans first; then, for each model x Persona, its agents and the humans paired with exactly the agents
    that completed (same people, same rounds: `human_reci`)."""
    parts = [h.assign(source="humans (all)")]
    for src, p in panel.groupby("source", sort=False):
        parts.append(p)
        parts.append(p.assign(reci=p.human_reci, source=f"{src} · paired humans"))
    return pd.concat(parts, ignore_index=True)


def analyse(paths: list[Path], out: Path) -> str:
    h = humans()
    panel, subjects = load_runs(paths)
    allp = with_paired_humans(h, panel)
    nemo = panel[(panel.persona == "nemotron") & panel.gender.isin(["Female", "Male"])]
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "1. Reciprocation rate (%) by treatment, 95% interval resampling agents": rates_table(allp),
        "2. Hot − Cold gap, rounds 19-20 (the paper's main window), 95% intervals": gap_table(allp),
        "3. Distribution of agents: never / sometimes / always reciprocate": types_table(allp),
        "4. Reciprocation by blocks of rounds (%), Hot vs Cold": rounds_table(allp),
        "5. Paper's Table 2 (LPM, controls age, female, education; clustered SE)": regression_table(allp),
        "6. Demographic vs Nemotron Persona, same participants (rounds 1-20)": persona_table(panel),
        "7. Exclusions per cell (humans: 3 of 534 failed the quiz)": exclusions_table(subjects),
        "8. Checks": checks_table(subjects, panel, demographics_r2(h)),
        "9. Sensitivity: Nemotron without participants of gender 'Other' or not said, rounds 19-20":
            gap_table(nemo.assign(source=nemo.source + " (gender F/M only)")) if len(nemo) else pd.DataFrame(),
    }
    text = ["# Results", "",
            "Theory (payoff-maximising second mover, paper Sec. 2): 0% in every cell. Surprise model: Hot ≥ Cold, "
            "gap larger in Low than in High. Only agents that completed the original screens are analysed. "
            "'paired humans' = the real participants paired with exactly those agents, in the same rounds.", ""]
    for i, (title, t) in enumerate(tables.items(), 1):
        t.to_csv(out / f"table{i}.csv", index=False)
        text += [f"## {title}", "", t.to_markdown(index=False) if len(t) else "(nothing to show)", ""]
    figure(allp[~allp.source.str.endswith("paired humans")], out / "fig_rounds19_20.png")
    text += ["![](fig_rounds19_20.png)", ""]
    (out / "results.md").write_text("\n".join(text))
    return "\n".join(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", type=Path, help="a batch folder (runs/<batch>) or a single run folder")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    if a.validate or not a.folder:
        problems = validate()
        print("Table 2 reproduced from the human data" if not problems else "\n".join(problems))
        if not a.folder:
            return
    runs = [a.folder] if (a.folder / "panel.csv").exists() else sorted(Path(p).parent for p in glob.glob(str(a.folder / "*/panel.csv")))
    print(analyse(runs, a.folder / "analysis"))


if __name__ == "__main__":
    main()
