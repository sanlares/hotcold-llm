"""Exploratory analyses, added on 2026-11-08 after the definitive run (not in docs/plan_de_analisis.md).

  uv run python -m hotcold.exploratory runs/<batch>      # -> runs/<batch>/analysis/exploratory.md, xtable*.csv, figures

Global summaries in percentages, the end-of-study questionnaire against the same humans, and the few person-level
measures that say something useful (does an agent resemble the real person it was paired with?), and the paper's
formal test of the surprise hypothesis (Sec. 4.1: Table 2 and the manipulation check of Table D.1). Same data and
definitions as hotcold.analysis: only agents that completed the original screens; a reciprocation decision is any
non-missing `reci`; rounds 1-20 unless a table says otherwise. Intervals resample agents (95%); for the agents of one
model they only reflect chance under this prompt and model version, since agents are not independent people.
"""

from __future__ import annotations

import argparse
import glob
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import CELLS, MIN_AGENTS, WINDOWS, _boot, bootstrap_rate, decisions, demographics_r2, humans, load_runs
from .personas import load_participants

HOT, COLD = "#eb6834", "#2a78d6"  # validated pair (dataviz skill palette, slots 2 and 1)
INK, SECOND, MUTED = "#0b0b0b", "#52514e", "#8a8984"  # text tokens; humans' reference lines use SECOND
HUMANS = "humans (all)"
QUESTIONS = {  # questionnaire field (raw Qualtrics column / agent column `q_<lower>`) -> how it is summarised
    "Expectation": "thought about type-1's choice: Yes %",
    "Temptation": "tempted to choose RIGHT, mean 0–7",
    "Complexity": "complexity, mean 0–10",
    "reciprocity1": "'I return favours', mean 0–10",
    "reciprocity2": "gift to a helpful stranger, mean £",
}


# --- parsing the questionnaire answers --------------------------------------------------------------------------
def scale(x) -> float:
    """'7', 7, '0 (Not at all tempted)', '10 (describe me perfectly)' -> the number; anything else -> NaN."""
    m = re.match(r"\s*(\d+)", str(x))
    return float(m.group(1)) if m and x == x else np.nan


def pounds(x) -> float:
    """reciprocity2: 'No present' -> 0, 'The present worth 15 Pounds' -> 15."""
    s = str(x)
    if s == "No present":
        return 0.0
    m = re.search(r"worth (\d+) Pounds", s)
    return float(m.group(1)) if m else np.nan


SURPRISE = {"No": 0, "A little": 1, "Yes": 2}  # surpriselevel, as in _create_HotCold_dataset.do


def questionnaire(subjects: pd.DataFrame) -> pd.DataFrame:
    """One row per completed agent and per real participant: source, ids, cell and the parsed answers."""
    ppl = load_participants()
    cell = humans().drop_duplicates("real_id").set_index("real_id").treat
    hum = pd.DataFrame({"source": HUMANS, "agent_id": ppl.real_id, "real_id": ppl.real_id,
                        "treat": ppl.real_id.map(cell), **{k: ppl[k] for k in [*QUESTIONS, "Surprise"]}})
    s = subjects[subjects.completed.astype(bool)]
    ag = pd.DataFrame({"source": s.source, "agent_id": s.agent_id, "real_id": s.real_id, "treat": s.treat,
                       **{k: s[f"q_{k.lower()}"] for k in [*QUESTIONS, "Surprise"]}})
    q = pd.concat([hum, ag], ignore_index=True)
    out = q[["source", "agent_id", "real_id", "treat"]].copy()
    out["expect_yes"] = q.Expectation.eq("Yes").astype(float).where(q.Expectation.notna())
    out["surprise"] = q.Surprise.map(SURPRISE)
    for k in ("Temptation", "Complexity", "reciprocity1"):
        out[k.lower()] = q[k].map(scale)
    out["gift"] = q.reciprocity2.map(pounds)
    return out


# --- helpers -----------------------------------------------------------------------------------------------------
def _ci(point: float, draws: np.ndarray, signed: bool = True) -> str:
    if point != point:
        return ""
    f = "{:+.0f}" if signed else "{:.0f}"
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return f"{f.format(100 * point)} [{f.format(100 * lo)}, {f.format(100 * hi)}]"


def _cells(d: pd.DataFrame) -> dict[str, tuple[float, np.ndarray]]:
    """Point share and bootstrap draws per treatment cell (cells are different agents: independent draws)."""
    out = {}
    for i, c in enumerate(CELLS):
        x = d[d.treat == c]
        out[c] = (x.reci.mean(), _boot(x, seed=i)) if len(x) else (np.nan, np.full(1000, np.nan))
    return out


def per_agent(d: pd.DataFrame, col: str = "reci") -> pd.Series:
    return d[d[col].notna()].groupby("agent_id")[col].mean()


def switch_rate(d: pd.DataFrame) -> float:
    """Share of an agent's consecutive decisions (in round order) that differ from the previous one, pooled."""
    x = d[d.reci.notna()].sort_values(["agent_id", "round"])
    same_agent = x.agent_id.eq(x.agent_id.shift())
    changes = (x.reci.ne(x.reci.shift()) & same_agent).sum()
    pairs = same_agent.sum()
    return changes / pairs if pairs else np.nan


def kind(rate: pd.Series) -> pd.Series:
    return pd.Series(np.select([rate == 0, rate == 1], ["never", "always"], "sometimes"), index=rate.index)


def r2_cells(d: pd.DataFrame) -> float:
    """Share of the differences in reciprocation between agents that the treatment cell explains."""
    per = d[d.reci.notna()].groupby("agent_id").agg(reci=("reci", "mean"), treat=("treat", "first"))
    if len(per) < 10 or per.reci.var(ddof=0) == 0:
        return np.nan
    fitted = per.groupby("treat").reci.transform("mean")
    return 1 - ((per.reci - fitted) ** 2).mean() / per.reci.var(ddof=0)


def _corr(a: pd.Series, b: pd.Series) -> str:
    j = pd.concat([a, b], axis=1).dropna()
    if len(j) < 10 or j.iloc[:, 0].std() == 0 or j.iloc[:, 1].std() == 0:
        return "—"
    return f"{j.iloc[:, 0].corr(j.iloc[:, 1]):+.2f}"


def _sources(allp: pd.DataFrame) -> list[str]:
    return list(dict.fromkeys(allp.source))


# --- tables --------------------------------------------------------------------------------------------------------
def overview_table(allp: pd.DataFrame) -> pd.DataFrame:
    """One line per source: overall rate, distance to the same humans, the two treatment effects, change over the
    session and how often an agent changes its choice."""
    rows = []
    for src in _sources(allp):
        p = allp[allp.source == src]
        d = decisions(p, "rounds 1-20")
        r, lo, hi = bootstrap_rate(d)
        cells = _cells(d)
        hot_cold = np.mean([cells[f"Hot-{c}"][0] - cells[f"Cold-{c}"][0] for c in ("Low", "High")])
        hot_cold_d = np.mean([cells[f"Hot-{c}"][1] - cells[f"Cold-{c}"][1] for c in ("Low", "High")], axis=0)
        high_low = np.mean([cells[f"{m}-High"][0] - cells[f"{m}-Low"][0] for m in ("Hot", "Cold")])
        high_low_d = np.mean([cells[f"{m}-High"][1] - cells[f"{m}-Low"][1] for m in ("Hot", "Cold")], axis=0)
        row = {"source": src, "agents": d.agent_id.nunique(),
               "reciprocate %": f"{100 * r:.0f} [{100 * lo:.0f}, {100 * hi:.0f}]" if r == r else ""}
        if src == HUMANS:
            row["same humans %"], row["distance to them, 4 cells (pp)"] = f"{100 * r:.0f}", "—"
        else:
            h = d[d.human_reci.notna()]
            dist = [abs(d[d.treat == c].reci.mean() - h[h.treat == c].human_reci.mean()) for c in CELLS
                    if (d.treat == c).any()]
            row["same humans %"] = f"{100 * h.human_reci.mean():.0f}"
            row["distance to them, 4 cells (pp)"] = f"{100 * np.mean(dist):.0f}"
        late, first = decisions(p, "rounds 19-20").reci.mean(), decisions(p, "round 1").reci.mean()
        fewest = min(d[d.treat == c].agent_id.nunique() for c in CELLS)
        few = fewest < MIN_AGENTS  # not interpreted: the comparisons between cells are left blank
        row |= {"Hot − Cold (pp)": "—" if few else _ci(hot_cold, hot_cold_d),
                "High − Low trust rate (pp)": "—" if few else _ci(high_low, high_low_d),
                "rounds 19-20 − round 1 (pp)": f"{100 * (late - first):+.0f}",
                "changes choice, % of consecutive decisions": f"{100 * switch_rate(d):.0f}",
                "fewest agents in a cell": fewest}
        if few:
            row["distance to them, 4 cells (pp)"] = "—"
        rows.append(row)
    return pd.DataFrame(rows)


def questionnaire_table(q: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for src, x in q.groupby("source", sort=False):
        hot = x[x.treat.str.startswith("Hot")]
        enough = len(hot) >= MIN_AGENTS
        rows.append({"source": src, "agents": len(x),
                     QUESTIONS["Expectation"]: round(100 * x.expect_yes.mean()),
                     "surprised by IN (Hot): Yes %": f"{100 * hot.surprise.eq(2).mean():.0f}" if enough else "—",
                     "… Yes or a little %": f"{100 * hot.surprise.ge(1).mean():.0f}" if enough else "—",
                     QUESTIONS["Temptation"]: round(x.temptation.mean(), 1),
                     QUESTIONS["Complexity"]: round(x.complexity.mean(), 1),
                     QUESTIONS["reciprocity1"]: round(x.reciprocity1.mean(), 1),
                     QUESTIONS["reciprocity2"]: round(x.gift.mean(), 1)})
    return pd.DataFrame(rows)


def surprise_table(q: pd.DataFrame) -> pd.DataFrame:
    """'Were you surprised … when he/she chose IN?' (Yes %) per cell. The paper's mechanism: in Hot, a low trust rate
    (28%) should surprise more than a high one (69%) (paper Table D.1)."""
    rows = []
    for src, x in q.groupby("source", sort=False):
        row, share = {"source": src}, {}
        for c in CELLS:
            y = x[x.treat == c]
            share[c] = round(100 * y.surprise.eq(2).mean()) if len(y) >= MIN_AGENTS else None
            row[f"{c} Yes %"] = "—" if share[c] is None else str(share[c])
        lo, hi = share["Hot-Low"], share["Hot-High"]
        row["Hot: Low − High (pp)"] = f"{lo - hi:+d}" if lo is not None and hi is not None else "—"
        rows.append(row)
    return pd.DataFrame(rows)


def say_do_table(allp: pd.DataFrame, q: pd.DataFrame) -> pd.DataFrame:
    """Correlation, across agents, between how often an agent reciprocated and what it said at the end."""
    rows = []
    for src in _sources(allp):
        rate = per_agent(decisions(allp[allp.source == src], "rounds 1-20"))
        x = q[q.source == src].set_index("agent_id")
        hot = x[x.treat.str.startswith("Hot")]
        rows.append({"source": src, "agents": len(rate),
                     "r with temptation to choose RIGHT": _corr(rate, x.temptation),
                     "r with 'I return favours'": _corr(rate, x.reciprocity1),
                     "r with gift to a stranger": _corr(rate, x.gift),
                     "r with surprise (Hot)": _corr(rate, hot.surprise)})
    return pd.DataFrame(rows)


def demography_table(allp: pd.DataFrame) -> pd.DataFrame:
    """Differences in reciprocation by the real person's gender, age and education (agents: their Persona's)."""
    gender = load_participants().set_index("real_id").Gender
    groups = {
        "women − men (pp)": lambda d: (d.gender == "Female", d.gender == "Male"),
        "age 24+ − age 18-23 (pp)": lambda d: (d.age >= 24, d.age <= 23),  # 23 = median age of the 396
        "master's or PhD − bachelor's (pp)": lambda d: (d.edu.isin(["Master", "PhD or above"]), d.edu == "Bachelor"),
    }
    rows = []
    for src in _sources(allp):
        d = decisions(allp[allp.source == src], "rounds 1-20").copy()
        d["gender"] = d.real_id.map(gender)
        row = {"source": src}
        for name, split in groups.items():
            a, b = split(d)
            da, db = d[a], d[b]
            if da.agent_id.nunique() < MIN_AGENTS or db.agent_id.nunique() < MIN_AGENTS:
                row[name] = ""
                continue
            row[name] = _ci(da.reci.mean() - db.reci.mean(), _boot(da, seed=1) - _boot(db, seed=2))
        rows.append(row)
    return pd.DataFrame(rows)


def person_table(allp: pd.DataFrame) -> pd.DataFrame:
    """Where differences between agents come from, and whether an agent resembles its own real person."""
    rows = []
    for src in _sources(allp):
        d = decisions(allp[allp.source == src], "rounds 1-20")
        row = {"source": src, "agents": d.agent_id.nunique(),
               "explained by the treatment cell %": _pct(r2_cells(d)),
               "explained by age, gender, education %": _pct(demographics_r2(d))}
        if src == HUMANS:
            row |= {"r with own human": "—", "same type as own human %": "—", "… expected by chance %": "—"}
        else:
            a, h = per_agent(d), per_agent(d, "human_reci")
            j = pd.concat([a.rename("a"), h.rename("h")], axis=1).dropna()
            ka, kh = kind(j.a), kind(j.h)
            chance = sum(ka.eq(k).mean() * kh.eq(k).mean() for k in ("never", "sometimes", "always"))
            row |= {"r with own human": _corr(j.a, j.h), "same type as own human %": round(100 * ka.eq(kh).mean()),
                    "… expected by chance %": round(100 * chance)}
        rows.append(row)
    return pd.DataFrame(rows)


def _boot_diff(a: pd.DataFrame, b: pd.DataFrame, reps: int = 1000, seed: int = 0) -> np.ndarray:
    """Bootstrap of share(a) − share(b) when a and b are decisions of the same agents (resample agents once)."""
    ga, gb = (x.groupby("agent_id").reci.agg(["sum", "count"]) for x in (a, b))
    ids = ga.index.union(gb.index)
    ga, gb = ga.reindex(ids, fill_value=0), gb.reindex(ids, fill_value=0)
    idx = np.random.default_rng(seed).integers(0, len(ids), size=(reps, len(ids)))
    with np.errstate(invalid="ignore", divide="ignore"):
        return (ga["sum"].values[idx].sum(1) / ga["count"].values[idx].sum(1)
                - gb["sum"].values[idx].sum(1) / gb["count"].values[idx].sum(1))


def history_table(allp: pd.DataFrame) -> pd.DataFrame:
    """Does the choice depend on what the previous round's type-1 participant chose (shown on the result screen)?"""
    rows = []
    for src in _sources(allp):
        d = allp[allp.source == src].sort_values(["agent_id", "round"]).copy()
        d["prev_in"] = d.groupby("agent_id").p1trust.shift()
        d = d[d.reci.notna() & d.prev_in.notna()]
        row = {"source": src}
        for mode in ("Hot", "Cold"):
            x = d[d.hot == int(mode == "Hot")]
            a, b = x[x.prev_in == 1], x[x.prev_in == 0]
            if min(a.agent_id.nunique(), b.agent_id.nunique()) < MIN_AGENTS:
                row |= {f"{mode}: after IN %": "—", f"{mode}: after OUT %": "—", f"{mode}: IN − OUT (pp)": "—"}
                continue
            row |= {f"{mode}: after IN %": f"{100 * a.reci.mean():.0f}", f"{mode}: after OUT %": f"{100 * b.reci.mean():.0f}",
                    f"{mode}: IN − OUT (pp)": _ci(a.reci.mean() - b.reci.mean(), _boot_diff(a, b))}
        rows.append(row)
    return pd.DataFrame(rows)


def _pct(x: float) -> str:
    return "—" if x != x else f"{100 * x:.1f}"


# --- humans vs the average model, per Persona ------------------------------------------------------------------------
PERSONAS = {"demographic": "demographic Persona", "nemotron": "Nemotron Persona"}


def averaged_models(allp: pd.DataFrame) -> list[str]:
    """Models that enter the average: 30+ agents in every cell with both Personas (rounds 1-20). This leaves out
    gpt-5-nano, which has almost no agents in Hot: with it, only the Cold average would rise."""
    d = decisions(allp[allp.source != HUMANS], "rounds 1-20")
    n = d.groupby(["model", "persona", "treat"]).agent_id.nunique().unstack("treat").reindex(columns=CELLS)
    full = n.ge(MIN_AGENTS).all(axis=1).groupby(level="model").all()
    both = n.groupby(level="model").size().eq(len(PERSONAS))
    return [m for m in dict.fromkeys(d.model) if full.get(m, False) and both.get(m, False)]


def model_cell_rates(allp: pd.DataFrame, window: str, models: list[str]) -> pd.DataFrame:
    """% reciprocate per cell for each model × Persona (decisions pooled within the model's agents, as table 1)."""
    d = decisions(allp[allp.model.isin(models)], window)
    return (100 * d.groupby(["persona", "model", "treat"]).reci.mean()).unstack("treat").reindex(columns=CELLS)


def persona_average_table(allp: pd.DataFrame) -> pd.DataFrame:
    """X11: the 396 humans vs the average of the models, one line per Persona. Every model weighs the same."""
    models = averaged_models(allp)
    hum = allp[allp.source == HUMANS]
    rows = []
    for w in WINDOWS:
        d = decisions(hum, w)
        row = {"window": w, "group": f"humans ({hum.real_id.nunique()})"}
        point, draws = {}, {}
        for i, c in enumerate(CELLS):
            x = d[d.treat == c]
            point[c], draws[c] = x.reci.mean(), _boot(x, seed=i)  # draws for the gap: independent seeds, as X1
            r, lo, hi = bootstrap_rate(x)  # the cell itself: the same interval as results.md, table 1
            row[c] = f"{100 * r:.0f} [{100 * lo:.0f}–{100 * hi:.0f}]"
        gap = np.mean([point[f"Hot-{c}"] - point[f"Cold-{c}"] for c in ("Low", "High")])
        gap_d = np.mean([draws[f"Hot-{c}"] - draws[f"Cold-{c}"] for c in ("Low", "High")], axis=0)
        rows.append(row | {"Hot − Cold (pp), mean of Low and High": _ci(gap, gap_d)})
        if not models:
            continue
        rates = model_cell_rates(allp, w, models)
        for persona, label in PERSONAS.items():
            r = rates.loc[persona]
            gaps = r[["Hot-Low", "Hot-High"]].values - r[["Cold-Low", "Cold-High"]].values
            g = gaps.mean(axis=1)  # one Hot − Cold per model
            row = {"window": w, "group": f"{label}, mean of {len(r)} models"}
            row |= {c: f"{r[c].mean():.0f} ({r[c].min():.0f}–{r[c].max():.0f})" for c in CELLS}
            rows.append(row | {"Hot − Cold (pp), mean of Low and High": f"{g.mean():+.0f} ({g.min():+.0f} to {g.max():+.0f})"})
    return pd.DataFrame(rows)


# --- the paper's formal tests (Sec. 4.1): Table 2 (tab2.do) and the surprise manipulation check (tabD1.do) ---------
def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b) (continued fraction, modified Lentz)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    if x > (a + 1) / (a + b + 2):  # the continued fraction converges fast on this side only
        return 1.0 - _betainc(b, a, 1.0 - x)
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)) / a
    f, c, d = 1.0, 1.0, 0.0
    for i in range(1000):
        m = i // 2
        if i == 0:
            num = 1.0
        elif i % 2 == 0:
            num = m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            num = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + num * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + num / (c if abs(c) > 1e-300 else 1e-300)
        f *= c * d
        if abs(1.0 - c * d) < 1e-14:
            break
    return front * (f - 1.0)


def t_pvalue(t: float, df: float) -> float:
    """Two-sided p-value of a t statistic with df degrees of freedom (Student t, as Stata reports it)."""
    if t != t or df <= 0:
        return np.nan
    if math.isinf(t):
        return 0.0
    return _betainc(df / 2, 0.5, df / (df + t * t))


def lpm(d: pd.DataFrame, y: str, terms: list[str], cluster: bool) -> dict:
    """OLS of y on `terms` + age + female + i.edu, as Stata's `reg` in tab2.do and tabD1.do: classical standard errors,
    or clustered by agent (CR1). Same design as hotcold.analysis.ols_cluster; it also returns the covariance (for
    sums of coefficients, Stata's lincom) and the degrees of freedom of the t test (clusters − 1, or n − k)."""
    d = d.dropna(subset=[y, *terms, "age", "female", "edu"])
    X = pd.DataFrame({t: d[t].astype(float) for t in terms}, index=d.index)
    X.insert(0, "const", 1.0)
    X["age"], X["female"] = d.age.astype(float), d.female.astype(float)
    edu = pd.get_dummies(d.edu, prefix="edu", dtype=float)
    X = pd.concat([X, edu.drop(columns=edu.columns[0])], axis=1)
    X = X.loc[:, X.std() > 0].assign(const=1.0)  # a model may have no variation in a control
    return _ols(X, d[y].astype(float).values, d.agent_id if cluster else None)


def _ols(X: pd.DataFrame, yv: np.ndarray, cluster_ids: pd.Series | None) -> dict:
    """OLS with Stata's standard errors: classical, or clustered (CR1) when cluster_ids is given."""
    Xv = X.values
    n, k = Xv.shape
    XtX_inv = np.linalg.pinv(Xv.T @ Xv)
    beta = XtX_inv @ Xv.T @ yv
    e = yv - Xv @ beta
    if cluster_ids is not None:
        codes, groups = pd.factorize(cluster_ids)
        S = np.zeros((len(groups), k))
        np.add.at(S, codes, Xv * e[:, None])  # each agent's score: its rows of X times its residuals, summed
        G = len(groups)
        V, df = XtX_inv @ (S.T @ S) @ XtX_inv * (G / (G - 1)) * ((n - 1) / (n - k)), G - 1
    else:
        V, df = XtX_inv * (e @ e) / (n - k), n - k
    return {"b": pd.Series(beta, X.columns), "V": pd.DataFrame(V, X.columns, X.columns), "df": df, "n": n}


def t_crit(df: float, level: float = 0.95) -> float:
    """The t value whose two-sided p-value is 1 − level (bisection on t_pvalue)."""
    lo, hi = 0.0, 50.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if t_pvalue(mid, df) > 1 - level else (lo, mid)
    return (lo + hi) / 2


def cell_margins(d: pd.DataFrame, cluster: bool) -> pd.DataFrame:
    """fig2.do: `reg reci i.treat [, vce(cluster id)]` and `margins treat`: each cell's rate with its 95% interval."""
    X = pd.get_dummies(d.treat).reindex(columns=CELLS, fill_value=0).astype(float)
    fit = _ols(X, d.reci.astype(float).values, d.agent_id if cluster else None)
    se, t = np.sqrt(np.diag(fit["V"].values)), t_crit(fit["df"])
    return pd.DataFrame({"rate": fit["b"], "lo": fit["b"] - t * se, "hi": fit["b"] + t * se})


def lincom(fit: dict, names: list[str]) -> tuple[float, float, float]:
    """Estimate, standard error and two-sided p-value of the sum of some coefficients."""
    if any(nm not in fit["b"] for nm in names):
        return (np.nan, np.nan, np.nan)
    est = float(fit["b"][names].sum())
    se = math.sqrt(max(float(fit["V"].loc[names, names].values.sum()), 0.0))
    t = est / se if se > 0 else (math.copysign(math.inf, est) if est != 0 else np.nan)
    return est, se, t_pvalue(t, fit["df"])


def table2(d: pd.DataFrame, cluster: bool) -> tuple[dict[str, tuple[float, float, float]], int]:
    """The paper's two specifications (Table 2): reci ~ Hot + High, and reci ~ Hot × High, with controls.
    Returns the estimates and the number of decisions used (rows with a missing control are dropped, as in Stata)."""
    d = d.assign(hot_x_high=d.hot * d.phigh)
    a = lpm(d, "reci", ["hot", "phigh"], cluster)
    b = lpm(d, "reci", ["hot", "phigh", "hot_x_high"], cluster)
    return {"Hot": lincom(a, ["hot"]), "High": lincom(a, ["phigh"]), "Hot in Low": lincom(b, ["hot"]),
            "Hot in High": lincom(b, ["hot", "hot_x_high"]), "Hot×High": lincom(b, ["hot_x_high"])}, a["n"]


def _diff(a: tuple, b: tuple) -> tuple[float, float, float]:
    """Agents' estimate − the paired humans' one, treating both as independent (an agent's choices are unrelated to its
    own human's: X6). Normal approximation (both samples have hundreds of degrees of freedom)."""
    est, se = a[0] - b[0], math.hypot(a[1], b[1])
    return est, se, (t_pvalue(est / se, 1e9) if se > 0 else np.nan)


def _stars(p: float) -> str:
    return "" if p != p else "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""


def _coef(x: tuple, strict: float) -> str:
    """'+10.3** (4.9)': estimate and standard error in percentage points; stars as in the paper; † = p < strict."""
    est, se, p = x
    if est != est:
        return "—"
    return f"{100 * est:+.1f}{_stars(p)}{' †' if p < strict else ''} ({100 * se:.1f})"


def _p(p: float) -> str:
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def _verdict(x: tuple, expected: int, strict: float) -> str:
    est, _, p = x
    if p != p:
        return "—"
    if p < 0.05:
        word = "supports" if np.sign(est) == expected else "against"
        return f"{word} ({_p(p)}){' †' if p < strict else ''}"
    return f"cannot tell ({_p(p)}, {'expected' if np.sign(est) == expected else 'opposite'} sign)"


def _testable(d: pd.DataFrame, cells: list[str] = CELLS, col: str = "reci") -> str:
    """'' when the test can be run; otherwise why not (as in the analysis plan: 30+ agents per cell, and variation)."""
    if min(d[d.treat == c].agent_id.nunique() for c in cells) < MIN_AGENTS:
        return f"a cell under {MIN_AGENTS} agents"
    if d[col].nunique() < 2:
        v = d[col].dropna()
        return "no variation" + (f" (always {'LEFT' if v.iloc[0] == 1 else 'RIGHT'})" if col == "reci" and len(v) else "")
    return ""


def surprise_test_long(allp: pd.DataFrame) -> pd.DataFrame:
    """Table 2 for every source and window, with the agents' difference from their paired humans (all in the csv)."""
    hum = allp[allp.source == HUMANS]
    rows = []
    for src in _sources(allp):
        p = allp[allp.source == src]
        paired = hum[hum.real_id.isin(p.real_id)]
        for w in WINDOWS:
            d, cluster = decisions(p, w), w != "round 1"  # tab2.do: round 1 has one decision per person
            row = {"source": src, "window": w, "decisions": len(d),
                   "agents per cell (HL/CL/HH/CH)": "/".join(str(d[d.treat == c].agent_id.nunique()) for c in CELLS)}
            why = _testable(d)
            row["not tested because"] = why
            if why:
                rows.append(row)
                continue
            est, row["decisions"] = table2(d, cluster)
            ref = table2(decisions(paired, w), cluster)[0] if src != HUMANS else None
            for k, (b, se, pv) in est.items():
                row |= {f"{k} (pp)": 100 * b, f"{k} SE": 100 * se, f"{k} p": pv}
            for k in ("Hot", "Hot×High"):
                if ref is not None:
                    b, se, pv = _diff(est[k], ref[k])
                    row |= {f"{k} − paired humans (pp)": 100 * b, f"{k} − paired humans p": pv}
            rows.append(row)
    return pd.DataFrame(rows)


def _row_tuple(r: pd.Series, k: str) -> tuple[float, float, float]:
    if f"{k} (pp)" not in r or r[f"{k} (pp)"] != r[f"{k} (pp)"]:
        return (np.nan, np.nan, np.nan)
    return (r[f"{k} (pp)"] / 100, r[f"{k} SE"] / 100, r[f"{k} p"])


def surprise_test_table(long: pd.DataFrame, strict: float) -> pd.DataFrame:
    """X8: the paper's test in its main window (rounds 19-20) and the verdict on each part of the hypothesis."""
    rows = []
    for _, r in long[long.window == "rounds 19-20"].iterrows():
        row = {"source": r.source, "agents per cell (HL/CL/HH/CH)": r["agents per cell (HL/CL/HH/CH)"]}
        if r["not tested because"]:
            rows.append(row | {"Hot": "—", "(a) Hot > Cold": r["not tested because"]})
            continue
        t = {k: _row_tuple(r, k) for k in ("Hot", "Hot in Low", "Hot in High", "Hot×High")}
        s = 0.0 if r.source == HUMANS else strict  # the correction is for the many models, not for the humans' test
        rows.append(row | {k: _coef(v, s) for k, v in t.items()}
                    | {"(a) Hot > Cold": _verdict(t["Hot"], +1, s), "(b) larger gap in Low": _verdict(t["Hot×High"], -1, s)})
    return pd.DataFrame(rows).fillna("")


def surprise_test_robustness(long: pd.DataFrame, strict: float) -> pd.DataFrame:
    """X9: the same coefficients in the paper's other windows, and the agents' difference from their paired humans."""
    rows = []
    for src, g in long.groupby("source", sort=False):
        row, s = {"source": src}, 0.0 if src == HUMANS else strict
        for w in ("round 1", "rounds 1-20"):
            r = g[g.window == w].iloc[0]
            for k in ("Hot", "Hot×High"):
                row[f"{w}: {k}"] = _coef(_row_tuple(r, k), s)
        r = g[g.window == "rounds 19-20"].iloc[0]
        for k in ("Hot", "Hot×High"):
            col = f"{k} − paired humans"
            if src == HUMANS or f"{col} (pp)" not in r or r[f"{col} (pp)"] != r[f"{col} (pp)"]:
                row[f"19-20: {col} (pp)"] = "—"
            else:
                row[f"19-20: {col} (pp)"] = f"{r[f'{col} (pp)']:+.1f}{_stars(r[f'{col} p'])} ({_p(r[f'{col} p'])})"
        rows.append(row)
    return pd.DataFrame(rows)


def manipulation_table(allp: pd.DataFrame, q: pd.DataFrame, strict: float) -> pd.DataFrame:
    """X10: in Hot, does the low trust rate (28%) surprise more than the high one (69%)? tabD1.do with the Baseline only:
    reg surprised i.phigh $ctrls if experiment==1 (one answer per person, classical standard errors)."""
    ctrl = allp.groupby(["source", "agent_id"], sort=False)[["age", "female", "edu"]].first()
    x = q[q.treat.fillna("").str.startswith("Hot")].join(ctrl, on=["source", "agent_id"])
    x = x.assign(phigh=x.treat.eq("Hot-High").astype(int), yes=x.surprise.eq(2).astype(float).where(x.surprise.notna()),
                 some=x.surprise.ge(1).astype(float).where(x.surprise.notna()))
    rows = []
    for src in _sources(allp):
        s = x[x.source == src]
        n = {c: s[s.treat == c].agent_id.nunique() for c in ("Hot-Low", "Hot-High")}
        row = {"source": src, "agents (Hot-Low/Hot-High)": f"{n['Hot-Low']}/{n['Hot-High']}"}
        for col, label in (("yes", "surprised"), ("some", "surprised or a little")):
            share = {c: s.loc[s.treat == c, col].mean() for c in n}
            row[f"{label} %: Low / High"] = (f"{100 * share['Hot-Low']:.0f} / {100 * share['Hot-High']:.0f}"
                                             if min(n.values()) >= MIN_AGENTS else "—")
            why = _testable(s, ["Hot-Low", "Hot-High"], col)
            if why:
                row[f"{label}: High − Low (pp)"] = why
                continue
            fit = lincom(lpm(s, col, ["phigh"], cluster=False), ["phigh"])
            row[f"{label}: High − Low (pp)"] = _coef(fit, 0.0 if src == HUMANS else strict)
        rows.append(row)
    return pd.DataFrame(rows)


# --- figures -------------------------------------------------------------------------------------------------------
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.labelcolor": INK, "axes.titlecolor": INK, "text.color": INK})
    return plt


def figure_overview(allp: pd.DataFrame, path: Path) -> None:
    """Left: % reciprocate, rounds 1-20. Right: Hot − Cold (average of Low and High). Humans as a reference line."""
    plt = _plt()
    srcs = [s for s in _sources(allp) if s != HUMANS]
    hum = decisions(allp[allp.source == HUMANS], "rounds 1-20")
    hcells = _cells(hum)
    h_rate = hum.reci.mean()
    h_gap = np.mean([hcells[f"Hot-{c}"][0] - hcells[f"Cold-{c}"][0] for c in ("Low", "High")])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 0.38 * len(srcs) + 1.6), sharey=True)
    for i, src in enumerate(srcs):
        d = decisions(allp[allp.source == src], "rounds 1-20")
        r, lo, hi = bootstrap_rate(d)
        a1.errorbar(100 * r, i, xerr=[[100 * (r - lo)], [100 * (hi - r)]], fmt="o", ms=5, color=INK, capsize=2, lw=1)
        cells = _cells(d)
        few = min(d[d.treat == c].agent_id.nunique() for c in CELLS) < MIN_AGENTS
        g = np.mean([cells[f"Hot-{c}"][0] - cells[f"Cold-{c}"][0] for c in ("Low", "High")])
        gd = np.mean([cells[f"Hot-{c}"][1] - cells[f"Cold-{c}"][1] for c in ("Low", "High")], axis=0)
        if few or g != g:
            a2.text(0, i, f"Hot cell under {MIN_AGENTS} agents", va="center", ha="center", color=SECOND, fontsize=8,
                    bbox={"facecolor": "white", "edgecolor": "none", "pad": 1})
            continue
        glo, ghi = np.quantile(gd, [0.025, 0.975])
        a2.errorbar(100 * g, i, xerr=[[100 * (g - glo)], [100 * (ghi - g)]], fmt="o", ms=5, color=INK, capsize=2, lw=1)
    for ax, v, label in ((a1, h_rate, f"humans {100 * h_rate:.0f}%"), (a2, h_gap, f"humans {100 * h_gap:+.0f} pp")):
        ax.axvline(100 * v, color=SECOND, lw=1.5, ls="--")
        ax.text(100 * v, -0.9, label, color=INK, ha="center", va="bottom", fontsize=8,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1})
        ax.grid(axis="x", color="#e6e5e0", lw=0.6)
        ax.set_axisbelow(True)
    a2.axvline(0, color=MUTED, lw=0.8, ls=":")
    a1.set_xlim(-3, 103)
    a1.set_xlabel("% reciprocate (LEFT), rounds 1–20")
    a2.set_xlabel("Hot − Cold (pp), mean of the Low and High gaps")
    a1.set_yticks(range(len(srcs)), srcs)
    a1.tick_params(axis="y", labelcolor=INK)
    a1.set_ylim(len(srcs) - 0.5, -1.2)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def figure_rounds(allp: pd.DataFrame, path: Path) -> None:
    """% reciprocate per round, Hot vs Cold, one panel per model; humans as wide light lines."""
    plt = _plt()
    agents = allp[(allp.source != HUMANS) & allp.model.notna()] if "model" in allp else allp.iloc[:0]
    models = list(dict.fromkeys(agents.model))
    if not models:
        return
    ncol = 4
    nrow = -(-len(models) // ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(12, 2.6 * nrow + 0.8), sharex=True, sharey=True, squeeze=False)
    hum = allp[(allp.source == HUMANS) & allp.reci.notna()]
    hum_curve = hum.assign(mode=np.where(hum.hot == 1, "Hot", "Cold")).groupby(["mode", "round"]).reci.mean()
    for ax, model in zip(axes.flat, models):
        for mode, color in (("Hot", HOT), ("Cold", COLD)):
            ax.plot(hum_curve[mode].index, 100 * hum_curve[mode].values, color=color, lw=5, alpha=0.18, solid_capstyle="round")
            for persona, ls in (("demographic", "-"), ("nemotron", "--")):
                x = agents[(agents.model == model) & (agents.persona == persona) & agents.reci.notna()
                           & (agents.hot == (mode == "Hot"))]
                if x.agent_id.nunique() < MIN_AGENTS:
                    continue
                c = x.groupby("round").reci.mean()
                ax.plot(c.index, 100 * c.values, color=color, lw=1.5, ls=ls)
        ax.set_title(model.split("/")[-1].split(":")[-1], fontsize=9)
        ax.set_ylim(-3, 103)
        ax.set_xticks([1, 5, 10, 15, 20])
        ax.grid(axis="y", color="#e6e5e0", lw=0.6)
    for ax in axes.flat[len(models):]:
        ax.set_visible(False)
    for ax in axes[:, 0]:
        ax.set_ylabel("% reciprocate")
    for ax in axes[-1, :]:
        ax.set_xlabel("round")
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=HOT, lw=1.5, label="Hot"), Line2D([], [], color=COLD, lw=1.5, label="Cold"),
               Line2D([], [], color=INK, lw=1.5, label="demographic Persona"),
               Line2D([], [], color=INK, lw=1.5, ls="--", label="Nemotron Persona"),
               Line2D([], [], color=MUTED, lw=5, alpha=0.35, label="humans (same color)")]
    fig.legend(handles=handles, loc="upper center", ncol=5, frameon=False, bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


# One color per Persona in every figure: green and magenta are far from the paper's orange and lilac, from this
# report's Hot orange and Cold blue, and from the humans' gray (dataviz validator: color-blind and normal vision pass)
PERSONA_STYLE = {"demographic": ("#4d9221", "o"), "nemotron": ("#c51b7d", "D")}


def figure_persona_average(allp: pd.DataFrame, path: Path) -> None:
    """% reciprocate per cell: the humans (with their 95% interval), and per Persona the average model (large mark)
    with each model as a small mark. Rounds 1-20 and 19-20."""
    plt = _plt()
    models = averaged_models(allp)
    if not models:
        return
    hum = allp[allp.source == HUMANS]
    xs = np.array([0, 1.3, 2.9, 4.2])  # a wider gap between the Low and the High trust rate
    off = {"humans": -0.25, "demographic": 0.0, "nemotron": 0.25}
    jitter = np.linspace(-0.07, 0.07, len(models))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    for ax, w in zip(axes, ("rounds 1-20", "rounds 19-20")):
        d = decisions(hum, w)
        for x, c in zip(xs, CELLS):
            r, lo, hi = bootstrap_rate(d[d.treat == c])
            xh = x + off["humans"]
            ax.errorbar(xh, 100 * r, yerr=[[100 * (r - lo)], [100 * (hi - r)]], fmt="o", ms=8, color=SECOND,
                        mec="white", mew=1.5, capsize=3, lw=1.2, zorder=3)
            ax.text(xh - 0.08, 100 * r, f"{100 * r:.0f}", ha="right", va="center", fontsize=7.5, color=INK)
        rates = model_cell_rates(allp, w, models)
        for persona, (color, marker) in PERSONA_STYLE.items():
            r = rates.loc[persona].reindex(models)
            for x, c in zip(xs, CELLS):
                xp = x + off[persona]
                ax.scatter(xp + jitter, r[c].values, s=14, marker=marker, color=color, alpha=0.55, lw=0, zorder=2)
                m = r[c].mean()
                ax.scatter([xp], [m], s=75, marker=marker, color=color, edgecolor="white", lw=1.5, zorder=4)
                ax.text(xp + 0.1, m, f"{m:.0f}", ha="left", va="center", fontsize=7.5, color=INK, zorder=5,
                        bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.5, "alpha": 0.8})
        ax.axvline(2.1, color="#e6e5e0", lw=0.8)
        ax.set_xticks(xs, ["Hot", "Cold", "Hot", "Cold"])
        for x, label in ((0.65, "low trust rate (28%)"), (3.55, "high trust rate (69%)")):
            ax.text(x, -0.13, label, transform=ax.get_xaxis_transform(), ha="center", va="top", color=SECOND, fontsize=8.5)
        ax.set_xlim(-0.6, 4.75)
        ax.set_ylim(-4, 104)
        ax.set_title(w.replace("rounds", "Rounds").replace("-", "–"), fontsize=10)
        ax.grid(axis="y", color="#e6e5e0", lw=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("% reciprocate (LEFT)")
    from matplotlib.lines import Line2D
    n = len(models)
    handles = [Line2D([], [], color=SECOND, marker="o", ls="", ms=7, label=f"humans ({hum.real_id.nunique()}), 95% interval"),
               *[Line2D([], [], color=PERSONA_STYLE[p][0], marker=PERSONA_STYLE[p][1], ls="", ms=7,
                        label=f"{PERSONAS[p]}, mean of {n} models") for p in PERSONAS],
               Line2D([], [], color=MUTED, marker="o", ls="", ms=3.5, alpha=0.7, label="small marks: each model")]
    fig.legend(handles=handles, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 1.0), fontsize=8.5)
    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    fig.savefig(path, dpi=150)
    plt.close(fig)


PAPER_HOT, PAPER_COLD = "#f1a340", "#998ec3"  # fig2.do: color("241 163 64") and color("153 142 195")


def _darker(color: str, k: float = 0.75) -> tuple:
    from matplotlib.colors import to_rgb
    return tuple(k * v for v in to_rgb(color))


def figure_paper_style(allp: pd.DataFrame, path: Path) -> None:
    """The paper's Fig. 2 (Baseline), drawn as fig2.do draws it, with two more bars in each treatment: the average
    model with the demographic and with the Nemotron Persona. Humans: the rate of each treatment from
    `reg reci i.treat` and its 95% interval (clustered by participant, except in round 1). Every model weighs the same
    in the averages (as X11); they carry no interval (the lowest and the highest model are in X11)."""
    plt = _plt()
    from matplotlib.patches import Patch
    models = averaged_models(allp)
    if not models:
        return
    hum = allp[allp.source == HUMANS]
    w = 0.1  # fig2.do: one bar of width .3 per treatment at Low/High ∓ .15; here that slot holds three bars of .1
    bars = (("humans", -w), ("demographic", 0.0), ("nemotron", w))
    paper = {"Hot": PAPER_HOT, "Cold": PAPER_COLD}
    rc = {"font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"], "axes.edgecolor": INK,
          "ytick.color": INK, "xtick.color": INK, "axes.titlecolor": INK, "text.color": INK}
    with plt.rc_context(rc):
        fig, axes = plt.subplots(1, 3, figsize=(12, 4.9))
        for ax, win, title in zip(axes, ("round 1", "rounds 19-20", "rounds 1-20"),
                                  ("Round 1", "Rounds 19-20", "Rounds 1-20")):
            hm = cell_margins(decisions(hum, win), cluster=win != "round 1")
            rates = model_cell_rates(allp, win, models)
            for xbase, level in ((0, "Low"), (1, "High")):
                for mode, centre in (("Hot", -0.15), ("Cold", 0.15)):
                    cell = f"{mode}-{level}"
                    for who, dx in bars:
                        x = xbase + centre + dx
                        color = paper[mode] if who == "humans" else PERSONA_STYLE[who][0]
                        v = hm.loc[cell, "rate"] if who == "humans" else rates.loc[who].reindex(models)[cell].mean() / 100
                        ax.bar(x, v, w, color=color, edgecolor=_darker(color), lw=0.6, zorder=2)
                        if who == "humans":
                            ax.vlines(x, hm.loc[cell, "lo"], hm.loc[cell, "hi"], color="black", lw=1.2, zorder=3)
                    ax.text(xbase + centre, -0.015, mode, ha="center", va="top", fontsize=10, style="italic",
                            transform=ax.get_xaxis_transform())  # which three bars are Hot and which Cold
            ax.set_xticks([0, 1], ["Low", "High"], fontsize=13)
            ax.tick_params(axis="x", length=0, pad=22)
            ax.tick_params(axis="y", labelsize=7, length=3)
            ax.set_yticks(np.arange(0, 0.71, 0.1), ["0"] + [f".{i}" for i in range(1, 8)])
            ax.set_ylim(0, 0.75)
            ax.set_xlim(-0.45, 1.45)
            ax.set_title(title, fontsize=12)
            ax.spines[["top", "right", "bottom"]].set_visible(False)  # fig2.do: xscale(noline)
            ax.grid(axis="y", color="#ececec", lw=0.8, ls="--")
            ax.set_axisbelow(True)
        axes[0].set_ylabel("Reciprocation rate", fontsize=13)
        n = len(models)
        handles = [Patch(facecolor=PAPER_HOT, edgecolor=_darker(PAPER_HOT), label="Hot, humans"),
                   Patch(facecolor=PAPER_COLD, edgecolor=_darker(PAPER_COLD), label="Cold, humans"),
                   *[Patch(facecolor=PERSONA_STYLE[p][0], edgecolor=_darker(PERSONA_STYLE[p][0]),
                           label=f"{PERSONAS[p]}, mean of {n} models") for p in PERSONAS]]
        fig.legend(handles=handles, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, 0.0), fontsize=12)
        fig.tight_layout(rect=(0, 0.08, 1, 1))
        fig.savefig(path, dpi=150)
        plt.close(fig)


# --- entry point ---------------------------------------------------------------------------------------------------
def explore(paths: list[Path], out: Path) -> str:
    panel, subjects = load_runs(paths)
    h = humans().assign(source=HUMANS)
    allp = pd.concat([h, panel], ignore_index=True)
    q = questionnaire(subjects)
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "X1. Overview, rounds 1-20: level, distance to the same humans, treatment effects, change over the session":
            overview_table(allp),
        "X2. End-of-study questionnaire (same questions as the humans)": questionnaire_table(q),
        "X3. Surprised when the type-1 participant chose IN (Yes %), by cell (shown with 30+ agents)": surprise_table(q),
        "X4. What they say vs what they do: correlation across agents (r) with their reciprocation rate":
            say_do_table(allp, q),
        "X5. Reciprocation by the real person's demographics (agents: their Persona's), rounds 1-20":
            demography_table(allp),
        "X6. Where differences between agents come from, and resemblance to the own real person": person_table(allp),
        "X7. Reaction to the previous round: % reciprocate after the previous type-1 participant chose IN vs OUT":
            history_table(allp),
    }
    long = surprise_test_long(allp)
    long.to_csv(out / "xtable8_numbers.csv", index=False)  # every window: estimate, standard error and p, unrounded
    tested =long[(long.window == "rounds 19-20") & (long.source != HUMANS) & long["not tested because"].eq("")]
    strict = 0.05 / max(len(tested), 1)  # Bonferroni over the model × Persona combinations that could be tested
    tables |= {
        "X8. The paper's formal test of the surprise hypothesis (Sec. 4.1, Table 2), rounds 19-20: linear probability "
        "model, percentage points": surprise_test_table(long, strict),
        "X9. Same test in the paper's other windows, and the agents against their paired humans":
            surprise_test_robustness(long, strict),
        "X10. Manipulation check (paper Table D.1, Baseline only): in Hot, does the low trust rate surprise more?":
            manipulation_table(allp, q, strict),
        "X11. Humans vs the average model with each Persona: % reciprocate by treatment": persona_average_table(allp),
    }
    left_out = [m.split("/")[-1].split(":")[-1] for m in dict.fromkeys(panel.model) if m not in averaged_models(allp)]
    notes = {
        "X1": "'same humans' = the real participants paired with these agents, in the same rounds. 'distance' = mean "
              "absolute difference over the 4 cells. Hot − Cold averages the Low and High gaps; High − Low averages Hot "
              "and Cold. A cell with fewer than 30 agents is shown but not interpreted (as in the analysis plan).",
        "X4": "r between −1 and +1; '—' when either side does not vary. Expected signs, as in people: negative with "
              "temptation, positive with the two reciprocity questions.",
        "X6": "'explained by' = share of the variance of the agents' reciprocation rates (R²). 'type' = never / "
              "sometimes / always. 'expected by chance' = agreement if agents and humans were paired at random with "
              "the same shares. The Personas carry no behaviour of the real person, so resemblance is not expected.",
        "X7": "Rounds 2-20. Each round ends with a result screen that shows what that round's type-1 participant "
              "chose. In Cold every round has a decision; in Hot only the rounds where the current type-1 participant "
              "chose IN. The interval resamples agents (the same agents are on both sides).",
        "X8": "As tab2.do (and results.md, table 5, which is pre-specified): reci on Hot and High, then on Hot × High; "
              "controls age, female and education (agents: their paired real person's); standard errors clustered by "
              "agent. 'Hot in High' = Hot + Hot×High (Stata's lincom). Stars as in the paper, two-sided: * p < 0.10, "
              "** p < 0.05, *** p < 0.01; † = p below 0.05 divided by the number of model × Persona combinations "
              f"tested ({len(tested)}, Bonferroni: p < {strict:.4f}). (a) Hot > Cold is read, as in the paper, from "
              "the Hot coefficient of the first specification (humans: +10.3, p = 0.037). (b) the Hot − Cold gap is "
              "larger in Low than in High: a negative Hot×High (humans: −11.2, p = 0.275, which the paper calls "
              "'negative as predicted but imprecisely estimated'). For the agents of one model, a p-value says "
              "whether the difference between treatments is larger than the differences between that model's agents "
              "under this prompt and this model version. It is not evidence about people (analysis plan, "
              "'Incertidumbre'). The paper uses rounds 19-20 as behaviour after learning; agents keep the whole "
              "session in one conversation, so for them it is not read as learning. Unrounded estimates, standard "
              "errors and p-values for every window: xtable8_numbers.csv.",
        "X9": "Same coefficients as X8 (round 1: one decision per agent, classical standard errors, as in the paper). "
              "'− paired humans' = the agents' coefficient minus that of the real participants paired with them, "
              "with both standard errors combined as if independent (normal approximation). The humans' own "
              "standard errors are large (rounds 19-20: Hot 4.9 pp, Hot×High 10.2 pp), so only large differences can "
              "be told apart.",
        "X10": "tabD1.do first runs `reg surpriseyes i.phigh $ctrls if experiment==1`, with the Baseline only; that "
               "is what is done here, with the controls of X8. The published Table D.1 pools Baseline and Beliefs, so "
               "its numbers differ from the humans' ones here. Question at the end of the study: surprised when the "
               "type-1 participant chose IN? (No / A little / Yes). One answer per agent, classical standard errors. "
               "Expected sign: negative (a high trust rate surprises less).",
        "X11": "Humans: the 396 participants, with a 95% interval that resamples people. Personas: for each model, "
               "the share of its decisions that reciprocate in that cell; then the mean over the models, each "
               "weighing the same (the model is the unit, as in the analysis plan). In parentheses: the lowest and "
               "the highest model, not an interval. Only models with 30+ agents in every cell with both Personas "
               f"enter the average; left out: {', '.join(left_out) or 'none'}. Hot − Cold: per model, the mean of "
               "the Low and High gaps, then averaged; for the humans, the same with their interval.",
    }
    text = ["# Exploratory analyses", "",
            "Added on 2026-11-08, **after** the definitive run. They are not in `docs/plan_de_analisis.md`, which was "
            "written before it. X1-X7 are description. X8-X10 (added on 2026-11-09) repeat the paper's formal tests "
            "with the agents: the regression is the pre-specified one (results.md, table 5), but the p-values, the "
            "verdicts, the comparison with the paired humans and the manipulation check were added after seeing "
            "the data. Only agents that completed the original screens. Intervals: 95%, resampling agents.", ""]
    for i, (title, t) in enumerate(tables.items(), 1):
        t.to_csv(out / f"xtable{i}.csv", index=False)
        text += [f"## {title}", "", t.to_markdown(index=False) if len(t) else "(nothing to show)", ""]
        if f"X{i}" in notes:
            text += [notes[f"X{i}"], ""]
    figure_overview(allp, out / "fig_overview.png")
    figure_rounds(allp, out / "fig_rounds.png")
    figure_persona_average(allp, out / "fig_personas.png")
    figure_paper_style(allp, out / "fig_paper_fig2.png")
    text += ["## Figures", "", "Black dots: agents, with 95% intervals; dashed line: the 396 humans.", "",
             "![](fig_overview.png)", "",
             f"Per round (lines with fewer than {MIN_AGENTS} agents are not drawn):", "", "![](fig_rounds.png)", "",
             "Humans vs the average model with each Persona (table X11): large marks are the means, small marks each "
             "model; the humans carry their 95% interval.", "", "![](fig_personas.png)", "",
             "The paper's Fig. 2 (Baseline) redrawn as fig2.do draws it, with two more bars in each treatment. Humans "
             "(orange: Hot; lilac: Cold): the rate of each treatment from `reg reci i.treat` and its 95% interval "
             "(standard errors clustered by participant, except in round 1). Green and magenta: the average model with "
             "the demographic and with the Nemotron Persona, each model weighing the same, as in X11; they carry no "
             "interval (X11 gives the lowest and the highest model).", "",
             "![](fig_paper_fig2.png)", ""]
    (out / "exploratory.md").write_text("\n".join(text))
    return "\n".join(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path, help="a batch folder (runs/<batch>) or a single run folder")
    a = ap.parse_args()
    runs = [a.folder] if (a.folder / "panel.csv").exists() else sorted(Path(p).parent for p in glob.glob(str(a.folder / "*/panel.csv")))
    print(explore(runs, a.folder / "analysis"))


if __name__ == "__main__":
    main()
