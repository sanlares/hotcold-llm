"""Literal screen texts and IN/OUT sequences, read straight from the authors' Qualtrics export (.qsf).

Screens are taken block by block (by Qualtrics block description), so the wording the agents see is
the wording the human participants saw. The only substitutions are:
  - piped embedded data (${e://Field/CRate}, ${e://Field/DRate});
  - the earnings figure (an image hosted on Tilburg's Qualtrics server), replaced by FIGURE_TEXT.
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The authors' replication package (not redistributed here). Set HOTCOLD_PACKAGE to point to your copy.
PACKAGE = Path(os.environ.get("HOTCOLD_PACKAGE") or ROOT / "Bibliography/hot_and_cold_data/replication package")
QSF = {"baseline": PACKAGE / "qualtrics/Baseline-SM/Baseline-second.qsf"}

N_ROUNDS = 20
MAX_QUIZ_ATTEMPTS = 6

# Text version of the earnings figure (paper, Fig. 1). Every number is also stated in the instructions text.
FIGURE_TEXT = (
    "[Figure: earnings in points]\n"
    "- Type-1 participant chooses OUT: type-1 participant earns 25, you earn 25.\n"
    "- Type-1 participant chooses IN and you choose LEFT: type-1 participant earns 35, you earn 35.\n"
    "- Type-1 participant chooses IN and you choose RIGHT: type-1 participant earns 12, you earn 50."
)
_IMG = re.compile(r"<img[^>]*>", re.I)


def clean(raw: str) -> str:
    """Qualtrics HTML -> plain text, keeping paragraph breaks."""
    s = _IMG.sub("\n" + FIGURE_TEXT + "\n", raw or "")
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "- ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = "\n".join(line.strip() for line in s.splitlines())
    return re.sub(r"\n{3,}", "\n\n", s).strip()


@dataclass(frozen=True)
class Question:
    qid: str
    tag: str
    text: str
    choices: tuple[str, ...]  # in display order
    statements: tuple[str, ...] = ()  # matrix rows (quiz item 1)


@dataclass(frozen=True)
class Block:
    name: str
    questions: tuple[Question, ...]

    def render(self, crate: str, drate: str, keys: dict[str, str] | None = None) -> str:
        """Screen text as a participant sees it, with answer options under each question.

        `keys` maps a question tag to the JSON field the agent answers in (shown as "(answer field: ...)").
        """
        keys = keys or {}
        parts = []
        for q in self.questions:
            part = q.text
            if q.statements:
                key = keys.get(q.tag, q.tag)
                rows = [f"- {s}  (answer field: {key}_{i})" for i, s in enumerate(q.statements, 1)]
                part += "\n\n" + "\n".join(rows) + "\nOptions for each row: " + " / ".join(q.choices)
            elif q.choices:
                field = f"  (answer field: {keys[q.tag]})" if q.tag in keys else ""
                part += "\n" + " / ".join(f"[ {c} ]" for c in q.choices) + field
            elif q.tag in keys:  # text entry
                part += f"\n[ ________ ]  (answer field: {keys[q.tag]})"
            if part:
                parts.append(part)
        text = "\n\n".join(parts)
        return text.replace("${e://Field/CRate}", crate).replace("${e://Field/DRate}", drate)


@dataclass(frozen=True)
class Sequence:
    group: int
    treatment: str  # "Hot" | "Cold"
    crate: str  # "28%" | "69%"
    drate: str
    choices: tuple[str, ...]  # MatchedChoice1..20, "IN" | "OUT"


class Materials:
    def __init__(self, experiment: str = "baseline"):
        survey = json.loads(QSF[experiment].read_text())
        elements = survey["SurveyElements"]
        questions = {e["PrimaryAttribute"]: e["Payload"] for e in elements if e["Element"] == "SQ"}
        blocks = next(e for e in elements if e["Element"] == "BL")["Payload"]
        blocks = blocks.values() if isinstance(blocks, dict) else blocks

        self.blocks: dict[str, Block] = {}
        for b in blocks:
            qids = [x["QuestionID"] for x in b.get("BlockElements", []) if x.get("Type") == "Question"]
            if not qids or b.get("Type") == "Trash":
                continue
            self.blocks[b["Description"]] = Block(b["Description"], tuple(_question(questions[q]) for q in qids))

        flow = next(e for e in elements if e["Element"] == "FL")["Payload"]
        randomizer = next(f for f in flow["Flow"] if f.get("Type") == "BlockRandomizer")
        self.sequences: dict[int, Sequence] = {}
        for item in randomizer["Flow"]:
            ed = {d["Field"]: d["Value"] for d in item["EmbeddedData"]}
            seq = Sequence(
                group=int(ed["Group"]),
                treatment=ed["Treatment"],
                crate=ed["CRate"],
                drate=ed["DRate"],
                choices=tuple(ed[f"MatchedChoice{r}"] for r in range(1, N_ROUNDS + 1)),
            )
            self.sequences[seq.group] = seq

    def block(self, name: str) -> Block:
        return self.blocks[name]


def _question(p: dict) -> Question:
    order = p.get("ChoiceOrder") or list(p.get("Choices", {}))
    choices = tuple(clean(p["Choices"][str(k)]["Display"]) for k in order) if p.get("Choices") else ()
    if p["QuestionType"] == "Matrix" and p.get("Answers"):
        answers = p.get("AnswerOrder") or list(p["Answers"])
        return Question(
            p["QuestionID"],
            p["DataExportTag"],
            clean(p["QuestionText"]),
            tuple(clean(p["Answers"][str(k)]["Display"]) for k in answers),
            statements=choices,
        )
    return Question(p["QuestionID"], p["DataExportTag"], clean(p["QuestionText"]), choices)


@lru_cache
def load(experiment: str = "baseline") -> Materials:
    return Materials(experiment)
