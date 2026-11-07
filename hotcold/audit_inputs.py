"""Check everything that will be sent to the agents, before spending anything (no model is called).

  uv run python -m hotcold.audit_inputs            # writes docs/auditoria_inputs.md; exit code 1 if a hard problem

For the two Personas of the final design and all 396 agents, it builds the system prompt, every screen of the
success path (scripted answers), the screens of quiz attempts 2-6, and every answer form, and checks:
  hard problems (must be fixed):  'nan'/'None'/empty values, Qualtrics placeholders left (${...}), wrong CRate/DRate,
                                  IN/OUT sequence different from the paired human's, demographics different from the
                                  raw export, the same Nemotron persona used twice
  cases to read by hand:          unusual demographics; Nemotron texts that mention another age, a job, or the
                                  other gender's pronouns; Nemotron personas without a name
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from .llm import ScriptedModel
from .materials import MAX_QUIZ_ATTEMPTS, load
from .personas import DATASET, DATASET_LABEL, build_personas, demographic_personas, load_participants
from .subject import Subject

HERE = Path(__file__).resolve().parents[1]
OUT = HERE / "docs/auditoria_inputs.md"
BAD_VALUE = re.compile(r"\b(?:nan|NaN|None|null|undefined)\b|\$\{|\{\w+\}")


class Recorder(ScriptedModel):
    """Scripted answers (quiz right, LEFT, valid questionnaire) that keeps every form it is asked to fill."""

    def __init__(self):
        super().__init__("left")
        self.schemas = []

    async def respond(self, system, messages, schema):
        self.schemas.append(schema)
        return await super().respond(system, messages, schema)


def sent_texts(p, m) -> tuple[list[str], Subject]:
    model = Recorder()
    s = Subject(p, m, model)
    asyncio.run(s.run())
    texts = [s.system] + [x["content"] for x in s.messages if x["role"] == "user"]
    texts += [json.dumps(sc) for sc in model.schemas]
    instr = "InstructionsHot" if s.hot else "InstructionsCold"
    for k in range(2, MAX_QUIZ_ATTEMPTS + 1):  # screens of later quiz attempts (not on the success path)
        texts.append(m.block(f"QuizQ{k}").render(s.seq.crate, s.seq.drate, s._quiz_keys(k)))
        texts.append(json.dumps(s._quiz_schema(k)))
    for b in ("Instructions2", instr, "QuizNo"):
        texts.append(m.block(b).render(s.seq.crate, s.seq.drate))
    return texts, s


def hard_checks(arm: str, personas, m, raw, human_seq) -> list[str]:
    problems = []
    for p in personas:
        texts, s = sent_texts(p, m)
        for t in texts:
            if hit := BAD_VALUE.search(t):
                problems.append(f"{arm} {p.agent_id}: '{hit.group()}' in: …{t[max(0, hit.start() - 60):hit.end() + 40]}…")
                break
        if not p.backstory().strip():
            problems.append(f"{arm} {p.agent_id}: empty Persona")
        crate, drate = s.seq.crate, s.seq.drate
        if int(crate[:-1]) + int(drate[:-1]) != 100 or crate not in ("28%", "69%"):
            problems.append(f"{arm} {p.agent_id}: CRate {crate} / DRate {drate}")
        shown = " ".join(texts)
        if f"is equal to {crate}" not in shown or f"is equal to {drate}" not in shown:
            problems.append(f"{arm} {p.agent_id}: trust rate {crate}/{drate} not on the screens")
        seq = [int(c == "IN") for c in s.seq.choices]
        if seq != human_seq.get(p.real_id):
            problems.append(f"{arm} {p.agent_id}: IN/OUT sequence differs from the human's p1trust")
        r = raw.loc[p.real_id]
        if (p.age, p.gender, p.education, p.group) != (int(r.Age), r.Gender, r.Education, int(r.Group)):
            problems.append(f"{arm} {p.agent_id}: demographics differ from the raw export")
        if f"aged {p.age}" not in p.backstory():
            problems.append(f"{arm} {p.agent_id}: real age not stated")
    return problems


AGE_IN_TEXT = re.compile(r"\b(\d{2})[- ]year[- ]old\b|\baged (\d{2})\b|\bat (\d{2}),|\bin (?:his|her|their) (\d0)s\b", re.I)
JOB = re.compile(r"\b(?:works? (?:full[- ]time|as an?)|full[- ]time (?:job|role|position)|employed as|"
                 r"his job|her job|their job|career as)\b", re.I)


def nemotron_cases(personas) -> tuple[list[str], list[str]]:
    from . import sources
    problems, cases = [], []
    refs = Counter(p.source_ref for p in personas)
    problems += [f"Nemotron persona {u} used {n} times" for u, n in refs.items() if n > 1]
    for p in personas:
        desc = p.backstory().split("A description of you:", 1)[-1]
        notes = []
        for m in AGE_IN_TEXT.finditer(desc):
            a = int(next(g for g in m.groups() if g))
            if (m.group(4) and not a <= p.age < a + 10) or (not m.group(4) and abs(a - p.age) > 2):
                notes.append(f"mentions age '{m.group()}' (real {p.age})")
        if JOB.search(desc):
            j = JOB.search(desc)
            notes.append(f"job wording: …{desc[max(0, j.start() - 50):j.end() + 50]}…".replace("\n", " "))
        she = len(re.findall(r"\b(?:she|her|hers)\b", desc, re.I))
        he = len(re.findall(r"\b(?:he|him|his)\b", desc, re.I))
        if p.gender == "Female" and he > she or p.gender == "Male" and she > he:
            notes.append(f"pronouns of the other gender (she/her {she}, he/him {he})")
        if p.gender not in ("Female", "Male"):
            notes.append(f"real gender '{p.gender}', text uses she/her {she}, he/him {he}")
        if p.backstory().startswith("You are aged") or p.backstory().startswith("You are a "):
            notes.append("no name found in the Nemotron text")
        if (p.match_age_diff or 0) >= 2 or not p.match_education:
            notes.append(f"match: age difference {p.match_age_diff}, same education {p.match_education}")
        if notes:
            cases.append(f"- `{p.agent_id}` ({p.gender}, {p.age}, {p.education}; Nemotron `{p.source_ref[:8]}`): "
                         + "; ".join(notes))
    return problems, cases


def demographic_cases(personas) -> list[str]:
    out = []
    for p in personas:
        notes = []
        if p.age >= 40:
            notes.append(f"age {p.age}")
        if p.gender not in ("Female", "Male"):
            notes.append(f"gender '{p.gender}'")
        if p.education == "Other":
            notes.append("education 'Other'")
        if notes:
            out.append(f"- `{p.agent_id}`: " + ", ".join(notes) + f" → \"{p.backstory()[:140]}…\"")
    return out


def main() -> int:
    from . import sources

    m = load("baseline")
    base = build_personas("baseline")
    raw = load_participants("baseline").set_index("real_id")
    ds = pd.read_csv(DATASET, usecols=["experiment", "id", "round", "p1trust"])
    ds = ds[ds.experiment == DATASET_LABEL["baseline"]].sort_values(["id", "round"])
    human_seq = {i: g.p1trust.fillna(-1).astype(int).tolist() for i, g in ds.groupby("id")}

    arms = {"demographic": demographic_personas(base)}
    if sources.NEMO_FILE.exists():
        arms["nemotron"] = sources.nemotron_personas(base)
    problems = []
    for arm, ps in arms.items():
        problems += hard_checks(arm, ps, m, raw, human_seq)
    nemo_problems, nemo_cases = nemotron_cases(arms["nemotron"]) if "nemotron" in arms else ([], [])
    problems += nemo_problems
    demo_cases = demographic_cases(arms["demographic"])

    lines = ["# Auditoría del input", "",
             "Generado por `uv run python -m hotcold.audit_inputs`. Revisa todo lo que se le manda a los agentes "
             "(mensaje de sistema, pantallas y formularios de respuesta) para los dos brazos del diseño final, "
             "sin llamar a ningún modelo.", "",
             f"- Brazos revisados: {', '.join(f'{a} ({len(p)} agentes)' for a, p in arms.items())}",
             f"- **Problemas que hay que corregir: {len(problems)}**", ""]
    lines += ["## Problemas", ""] + ([f"- {x}" for x in problems] or ["Ninguno."]) + [""]
    lines += ["## Casos para leer a mano", "",
              "No son errores: son agentes cuya Persona conviene mirar antes de correr.", "",
              f"### Persona demográfica ({len(demo_cases)})", ""] + demo_cases + [""]
    if "nemotron" in arms:
        diffs = Counter(p.match_age_diff for p in arms["nemotron"])
        lines += [f"### Nemotron ({len(nemo_cases)})", "",
                  "Calidad del emparejamiento: diferencia de edad " + ", ".join(f"{k} años: {v}" for k, v in sorted(diffs.items()))
                  + f"; misma educación: {sum(p.match_education for p in arms['nemotron'])} de {len(arms['nemotron'])}; "
                  "todos son estudiantes.", ""] + nemo_cases + [""]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines))
    print(f"{len(problems)} problems, {len(demo_cases)} demographic and {len(nemo_cases)} Nemotron cases to read -> {OUT}")
    for x in problems[:20]:
        print(" ", x)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
