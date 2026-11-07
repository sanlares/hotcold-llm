"""Persona sources built from external, real or documented material instead of hand-written text.
Only `nemotron` is part of the final design; the others were explored in the pilots (fixed 20 pilot agents).

  prism          the basic Persona + the real self-description of a UK PRISM participant (Kirk et al. 2024)
                 matched on gender, age band and education (same 20 pilot agents, so human data stays comparable)
  nemotron       FINAL DESIGN, any sample of the 396: real demographics of the participant + the narrative fields of
                 a matched synthetic UK student (NVIDIA Nemotron-Personas-UK: census-grounded demographics, Big Five
                 drawn from regional scores, text written by Gemma 4 31B); each Nemotron persona used once
  twin-summary   a real US participant of Twin-2K-500 (Toubia et al. 2025): the authors' persona summary with the
                 trust, ultimatum and dictator game results removed
  twin-narrative the same information rewritten as a first-person account by an LLM with a fixed prompt
                 (see make_twin_narratives.py; texts stored in data/derived/twin_narratives.yaml)
  twin-qa        all of the participant's survey questions and answers, games removed (long; Twin trust game only)
  twin-demographic demographics only (baseline for the Twin validation)

Twin agents play hot-cold with the treatment and IN/OUT sequence of the pilot agent in the same position, so the
20 sequences are identical across sources. Downloaded data lives in data/external/ (see README).
"""

from __future__ import annotations

import json
import random
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from .personas import EDUCATION_LINE, Persona, gender_line, render_backstory, without_invented

HERE = Path(__file__).resolve().parents[1]
EXT = HERE / "data/external"
DERIVED = HERE / "data/derived"

PRISM_QUESTION = (
    "Please briefly describe your values, core beliefs, guiding principles in life, or other things that are "
    "important to you. For example, you might include values you'd want to teach to your children or qualities "
    "you look for in friends. There are no right or wrong answers. Please do not provide any personally "
    "identifiable details like your name, address or email. Please write 2-5 sentences in your own words."
)

# Twin-2K-500 items that are economic games (or thoughts about them): never shown to an agent.
TWIN_GAME_QIDS = {"QID117", "QID118", "QID119", "QID120", "QID121", "QID122", "QID224", "QID231", "QID271", "QID272"}
TWIN_GAME_SECTIONS = ("ultimatum game", "trust game", "dictator game")


# --- PRISM ----------------------------------------------------------------------------------------------------
def _age_band(age: int) -> str:
    for lo, hi, band in [(18, 24, "18-24"), (25, 34, "25-34"), (35, 44, "35-44"), (45, 54, "45-54"), (55, 64, "55-64")]:
        if lo <= age <= hi:
            return band + " years old"
    return "65+ years old"


PRISM_EDU = {
    "High school or below": ["Completed Secondary School", "Some Secondary", "Vocational"],
    "Bachelor student": ["Some University but no degree", "Completed Secondary School"],
    "Master student": ["University Bachelors Degree", "Graduate / Professional degree"],
    "PhD student or above": ["Graduate / Professional degree", "University Bachelors Degree"],
    "Other": ["Vocational", "Some University but no degree"],
}


@lru_cache
def prism_uk() -> pd.DataFrame:
    rows = [json.loads(line) for line in (EXT / "prism/survey.jsonl").open()]
    df = pd.DataFrame(rows)
    df = df[df.location.map(lambda d: d.get("reside_country")) == "United Kingdom"].copy()
    df["words"] = df.self_description.fillna("").str.split().str.len()
    return df[df.words >= 10]


def prism_personas(base: list[Persona], seed: int = 0) -> list[Persona]:
    """Match each agent to a distinct UK PRISM participant; closest match first, ties broken by seed."""
    pool = prism_uk()
    rng = random.Random(seed)
    used, out = set(), []
    for p in base:
        def score(r):
            s = 0
            s += 4 * (p.gender in ("Female", "Male") and r.gender == p.gender)
            s += 3 * (r.age == _age_band(p.age))
            s += 2 * (r.employment_status == "Student")
            s += 1 * (r.education in PRISM_EDU[p.education])
            return s
        cand = pool[~pool.user_id.isin(used)].copy()
        cand["s"] = cand.apply(score, axis=1)
        best = cand[cand.s == cand.s.max()]
        r = best.iloc[rng.randrange(len(best))]
        used.add(r.user_id)
        q = _clone(p, "prism", r.user_id)
        q.override = (render_backstory(p) + "\n\nIn an earlier survey you were asked: \"" + PRISM_QUESTION
                      + "\"\nYou wrote: \"" + r.self_description.strip() + "\"")
        out.append(q)
    return out


# --- Nemotron-Personas-UK ----------------------------------------------------------------------------------------
NEMO_EDU = {
    "High school or below": ["A level or equivalent", "GCSE level or below"],
    "Bachelor student": ["A level or equivalent"],
    "Master student": ["Degree or other higher education"],
    "PhD student or above": ["Degree or other higher education"],
    "Other": ["Apprenticeship", "Other or unknown", "A level or equivalent"],
}
NEMO_FIELDS = ["persona", "cultural_background", "professional_persona", "hobbies_and_interests",
               "career_goals_and_ambitions"]


NEMO_FILE = EXT / "nemotron_uk/train-00000-of-00007.parquet"  # one of 7 random shards (~143k personas)
NEMO_REVISION = "0bb75b1469b90795eb56fa8a64927dac77dd0a11"  # Hugging Face commit of the file used (2026-10-20)

# Who counts as a student in Nemotron: the census occupation is "Does not apply" (not in employment) AND the
# text describes the person as studying now. A bare "student" is not enough: older personas mention "student
# support services", "student mentorship" or being a "former student".
_NOT_SELF = (r"(?! (?:support|services|development|loan|welfare|recruitment|union|accommodation|experience|"
             r"engagement|finance|wellbeing|assessment|mentorship|of faith|of life|of history|of human))")
NEMO_STUDENT = re.compile(
    r"\b(?:(?:is|as|and|was) an? (?:[\w'-]+,? ){0,3}student\b" + _NOT_SELF
    + r"|(?:current|full-time|part-time|mature|university|undergraduate|postgraduate|doctoral|PhD|master'?s) student\b"
    + _NOT_SELF + r"|turned student\b|studying (?:for|towards)\b"
    + r"|(?:his|her|their) (?:studies|dissertation|thesis|coursework|lectures|university course)\b)", re.I)
NEMO_NOT_STUDENT = re.compile(r"\b(?:former|retired|ex-) student|student days|after graduating|graduated (?:from|with)", re.I)

# Matching tiers, tried in order: (max |age difference|, education must match). Always a student.
NEMO_TIERS = [(1, True), (2, True), (3, True), (5, True), (1, False), (2, False), (3, False), (5, False),
              (8, False), (12, False), (99, False)]


@lru_cache
def nemotron_pool() -> pd.DataFrame:
    d = pd.read_parquet(NEMO_FILE)
    text = d.persona + " " + d.professional_persona
    d["student"] = (d.occupation == "Does not apply") & text.str.contains(NEMO_STUDENT) & ~text.str.contains(NEMO_NOT_STUDENT)
    return d[d.student].reset_index(drop=True)


@lru_cache
def nemotron_assignment(seed: int = 0) -> dict[str, dict]:
    """Nemotron persona for every real participant (all 396), computed once so that any sample -- a pilot of
    20 or the full run -- gives each agent the same match. Each Nemotron persona is used at most once. Scarcer
    profiles (older participants) are matched first; within a tier the closest age wins, ties broken by seed."""
    from .personas import build_personas

    pool = nemotron_pool()
    rng = random.Random(seed)
    people = sorted(build_personas("baseline"), key=lambda p: (-p.age, int(p.agent_id.rsplit("_", 1)[1])))
    used, out = set(), {}
    for p in people:
        sexes = [p.gender] if p.gender in ("Female", "Male") else ["Female", "Male"]
        base = pool[pool.sex.isin(sexes) & ~pool.uuid.isin(used)]
        diff = base.age.sub(p.age).abs()
        edu_ok = base.education_level.isin(NEMO_EDU[p.education])
        for window, need_edu in NEMO_TIERS:
            cand = base[(diff <= window) & (edu_ok | (not need_edu))]
            if len(cand):
                break
        else:
            raise ValueError(f"no Nemotron student left for {p.agent_id}")
        best = cand[diff[cand.index] == diff[cand.index].min()]
        r = best.loc[best.index[rng.randrange(len(best))]]
        used.add(r.uuid)
        out[p.agent_id] = {"row": r, "age_diff": int(abs(r.age - p.age)),
                           "education": bool(r.education_level in NEMO_EDU[p.education])}
    return out


def nemotron_text(p: Persona, r) -> str:
    name = _nemotron_name(r)
    facts = " ".join([gender_line(p, name), f"You live in {r.municipality} ({r.region}) and you are a student.",
                      EDUCATION_LINE[p.education], "Now and then you take part in paid online studies on Prolific."])
    return facts + "\n\nA description of you:\n\n" + "\n\n".join(r[f].strip() for f in NEMO_FIELDS)


def nemotron_personas(base: list[Persona], seed: int = 0) -> list[Persona]:
    """Real demographics of each agent + the narrative fields of its matched Nemotron persona. The agent keeps
    its own treatment and IN/OUT sequence."""
    match = nemotron_assignment(seed)
    out = []
    for p in base:
        m = match[p.agent_id]
        q = without_invented(p, "nemotron")
        q.source_ref, q.override = m["row"].uuid, nemotron_text(p, m["row"])
        q.match_age_diff, q.match_education, q.match_student = m["age_diff"], m["education"], True
        out.append(q)
    return out


_VERB = r"(?:is|has|was|uses|enjoys|identifies|spends|keeps|prefers|balances|finds|grew|aims|hopes|intends|combines|loves)"


def _nemotron_name(r) -> str:
    """The persona's first name, as used throughout its texts ("... Thomas is ..."); most frequent subject."""
    from collections import Counter

    text = " ".join(r[f] for f in NEMO_FIELDS)
    names = Counter(re.findall(rf"\b([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\s+{_VERB}\b", text))
    for w in ("He", "She", "They", "This", "The", "Her", "His", "Born", "As", "While", "Outside", "When"):
        names.pop(w, None)
    if names:
        return names.most_common(1)[0][0]
    first = re.match(r"([A-Z][a-z]+(?:-[A-Z][a-z]+)?) (?:is|was)\b", r.persona.strip())  # "Mohsin is a ..."
    return first.group(1) if first else ""  # no name: the facts line is written without one


# --- Twin-2K-500 --------------------------------------------------------------------------------------------------
@lru_cache
def twin_people() -> pd.DataFrame:
    d = pd.read_parquet(EXT / "twin/persona_chunk_001.parquet")
    d["pid"] = d.pid.astype(int)
    return d


def twin_sample(n: int = 20, seed: int = 0) -> list[int]:
    """First n of a seeded shuffle, so a larger sample always contains the smaller one."""
    pids = sorted(twin_people().pid.tolist())
    random.Random(seed).shuffle(pids)
    return pids[:n]


def twin_summary(pid: int) -> str:
    """Authors' persona summary with the economic-game paragraphs removed."""
    text = twin_people().set_index("pid").loc[pid, "persona_summary"]
    paras = text.split("\n\n")
    keep = [x for x in paras if not any(f"person's {g}" in x.lower() for g in TWIN_GAME_SECTIONS)]
    out = "\n\n".join(keep)
    assert "trust game" not in out.lower() and "dictator" not in out.lower() and "ultimatum" not in out.lower()
    return out


def twin_demographics(pid: int) -> str:
    return twin_summary(pid).split("\n\n")[1]  # "The person's demographics are the following..."


def twin_qa(pid: int) -> str:
    """All questions and answers (waves 1-4), in the dataset's own text layout, games removed."""
    blocks = json.loads(twin_people().set_index("pid").loc[pid, "persona_json"])
    lines = []
    for b in blocks:
        for q in b.get("Questions", []):
            text = re.sub(r"\s+", " ", q.get("QuestionText", "")).strip()
            if q.get("QuestionID") in TWIN_GAME_QIDS or "(anonymous) person" in text or "keep for yourself" in text:
                continue  # economic games and the thoughts reported while playing them
            ans = q.get("Answers")
            if not ans:
                continue
            rows = q.get("Rows")
            if rows and isinstance(ans, dict) and isinstance(ans.get("SelectedText"), list):
                pairs = "\n".join(f"- {r}: {a}" for r, a in zip(rows, ans["SelectedText"]))
                lines.append(f"Q: {text}\n{pairs}")
            else:
                lines.append(f"Q: {text}\nA: {_answer_text(ans)}")
    return "\n\n".join(lines)


def _answer_text(ans) -> str:
    if isinstance(ans, dict):
        if "SelectedText" in ans:
            v = ans["SelectedText"]
            return "; ".join(map(str, v)) if isinstance(v, list) else str(v)
        if "Text" in ans:
            return str(ans["Text"])
        return "; ".join(f"{k}: {_answer_text(v)}" for k, v in ans.items() if k not in ("SelectedByPosition",))
    if isinstance(ans, list):
        return "; ".join(_answer_text(a) for a in ans)
    return str(ans)


@lru_cache
def twin_narratives() -> dict:
    path = DERIVED / "twin_narratives.yaml"
    return yaml.safe_load(path.read_text())["narratives"] if path.exists() else {}


TWIN_INTRO = {
    "twin-summary": "You are the person described below. Everything in it is real information about you, from a "
                    "long survey you completed.\n\n",
    "twin-qa": "You are the person whose survey answers are listed below. These are your own answers to a long "
               "survey you completed.\n\n",
    "twin-demographic": "You are the person described below.\n\n",
    "twin-narrative": "",
}


def twin_text(pid: int, fmt: str) -> str:
    body = {"twin-summary": twin_summary, "twin-qa": twin_qa, "twin-demographic": twin_demographics,
            "twin-narrative": lambda x: twin_narratives()[int(x)]}[fmt](pid)
    return TWIN_INTRO[fmt] + body


def twin_personas(base: list[Persona], fmt: str, seed: int = 0) -> list[Persona]:
    """Twin participant i plays hot-cold with the treatment and sequence of pilot agent i."""
    out = []
    for p, pid in zip(base, twin_sample(len(base), seed)):
        q = _clone(p, fmt, str(pid))
        q.agent_id, q.real_id = f"twin_{pid}", f"twin-2k-500:{pid}"
        q.override = twin_text(pid, fmt)
        out.append(q)
    return out


# --- helpers ---------------------------------------------------------------------------------------------------------
def _clone(p: Persona, source: str, ref: str) -> Persona:
    from dataclasses import replace

    return replace(p, source=source, source_ref=str(ref), seq_from=p.agent_id, hobbies=list(p.hobbies))


def build(source: str, base: list[Persona], seed: int = 0) -> list[Persona]:
    if source == "prism":
        return prism_personas(base, seed)
    if source == "nemotron":
        return nemotron_personas(base, seed)
    if source.startswith("twin-"):
        return twin_personas(base, source, seed)
    raise ValueError(source)
