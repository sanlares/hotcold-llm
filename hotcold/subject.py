"""One second mover going through the Baseline second-mover survey, replicating its Survey Flow.

Flow (Baseline-second.qsf): Welcome -> Instructions -> Instructions{Hot,Cold} -> quiz (up to 6 attempts;
after a wrong attempt: Instructions2 -> Instructions{Hot,Cold} -> next quiz; after the 6th: QuizNo, excluded)
-> Start -> 20 rounds -> Payment -> Questionnaire -> [added] Debrief.
  Hot,  type-1 IN : HotQuestion{r}IN (decision) -> Result{r}.2 (LEFT) / Result{r}.3 (RIGHT)
  Hot,  type-1 OUT: HotQuestion{r}OUT -> Result{r}.1 (no decision)
  Cold, any       : ColdQuestion{r} (decision) -> Result{r}.1 (OUT) / Result{r}.2 / Result{r}.3 (IN)
Consent, Prolific ID and the "Are you a student?" prescreen are skipped.

The whole session is one conversation: the agent keeps every screen and every own answer in memory.
Screens that only ask for "Next" are accumulated and shown together with the next screen that needs an answer.

Two kinds of bad answers are kept apart:
  - technical failure (empty, cut off, unreadable, invented field, value outside the offered options): the same
    request is sent again, up to FORMAT_RETRIES times, as if the page had not loaded; then the agent is flagged
    (drop_stage 9). Every attempt is logged.
  - an odd but well-formed answer (e.g. age "-28"): kept as it is. It is the model's behaviour; analysis flags it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

from .llm import FatalAPIError
from .materials import MAX_QUIZ_ATTEMPTS, N_ROUNDS, Materials
from .personas import Persona

SCREEN_SEPARATOR = "\n\n--- next screen ---\n\n"
FORMAT_RETRIES = 2

SYSTEM_TEMPLATE = """{backstory}

You are now taking part in an online study on Prolific, on your computer. You will see the study's screens in order, as text: pictures are described in square brackets, and the options you can click are shown in square brackets, like [ Next ]. Several screens that only need a click on "Next" may be shown together, separated by "--- next screen ---". When a screen asks you for an answer, give it in the requested format. Answer as yourself."""

# Added after the original questionnaire, when no decision can be affected any more (not part of the .qsf).
DEBRIEF_SCREEN = """Two last questions

These questions are asked after the study has ended.

How did you decide between LEFT and RIGHT? Please describe it in a few sentences.
[ ________ ]  (answer field: how_decided)

Have you seen or read about this study, or a very similar one, before?
[ Yes ] / [ No ]  (answer field: seen_before)

If yes, which one? (Leave empty if no.)
[ ________ ]  (answer field: seen_which)"""

DEBRIEF_SCHEMA_PROPS = {
    "how_decided": ("string", None, "How did you decide between LEFT and RIGHT? Please describe it in a few sentences."),
    "seen_before": ("string", ["Yes", "No"], "Have you seen or read about this study, or a very similar one, before?"),
    "seen_which": ("string", None, "If yes, which one? (Leave empty if no.)"),
}

QUESTIONNAIRE_KEYS = {
    "Expectation": "expectation", "Surprise": "surprise", "Temptation": "temptation",
    "Complexity": "complexity", "reciprocity1": "reciprocity1", "reciprocity2": "reciprocity2",
    "Age": "age", "Gender": "gender", "Education": "education", "Comment": "comment",
}


class SubjectError(RuntimeError):
    pass


@dataclass
class Result:
    agent_id: str
    real_id: str
    treatment: str
    crate: str
    group: int
    completed: bool = False  # finished every original screen (questionnaire included), as finished==1 in the dataset
    drop_stage: int | None = None  # 2 = failed the quiz six times (as in the dataset); 9 = technical error
    error: str = ""
    quiz_attempts: int = 0
    quiz_answers: list[dict] = field(default_factory=list)
    rounds: list[dict] = field(default_factory=list)  # round, p1trust, choice, reci
    questionnaire: dict = field(default_factory=dict)
    debrief: dict = field(default_factory=dict)
    debrief_error: str = ""  # a technical failure on the added last screen does not undo a completed session
    usage: dict = field(default_factory=dict)
    calls: int = 0  # answered screens
    requests: int = 0  # requests sent, including technical retries
    format_retries: int = 0
    seconds: float = 0.0
    model_versions: list[str] = field(default_factory=list)  # model names reported by the provider


class Subject:
    def __init__(self, persona: Persona, materials: Materials, model, explain: bool = False,
                 log_call: Callable[[dict], None] | None = None):
        self.explain = explain  # diagnostic arm: also ask for a one-sentence reason with each choice
        self.p = persona
        self.m = materials
        self.model = model
        self.log_call = log_call or (lambda rec: None)
        self.seq = materials.sequences[persona.group]
        assert (self.seq.treatment, self.seq.crate) == (persona.treatment, persona.crate), persona.agent_id
        self.hot = self.seq.treatment == "Hot"
        self.system = SYSTEM_TEMPLATE.format(backstory=persona.backstory())
        self.messages: list[dict] = []
        self.pending: list[str] = []
        self.res = Result(persona.agent_id, persona.real_id, self.seq.treatment, self.seq.crate, self.seq.group)

    # --- conversation helpers --------------------------------------------------------------------------
    def show(self, block: str) -> None:
        self.pending.append(self.m.block(block).render(self.seq.crate, self.seq.drate))

    async def ask(self, block: str, keys: dict[str, str], schema: dict, screen: str | None = None) -> dict:
        if screen is None:
            screen = self.m.block(block).render(self.seq.crate, self.seq.drate, keys)
        content = SCREEN_SEPARATOR.join(self.pending + [screen])
        self.pending = []
        self.messages.append({"role": "user", "content": content})
        for attempt in range(FORMAT_RETRIES + 1):
            t0 = time.time()
            answer, meta = await self.model.respond(self.system, self.messages, schema)
            if answer is not None and (bad := invalid(answer, schema)):
                answer, meta = None, {**meta, "stop_reason": f"invalid: {bad}"}
            self.res.requests += 1
            for k, v in meta.get("usage", {}).items():
                self.res.usage[k] = self.res.usage.get(k, 0) + (v or 0)
            version = meta.get("model_version")
            if version and version not in self.res.model_versions:
                self.res.model_versions.append(version)
            self.log_call({"agent_id": self.p.agent_id, "screen": block, "attempt": attempt + 1,
                           "ok": answer is not None, "latency_s": round(time.time() - t0, 2),
                           "stop_reason": meta.get("stop_reason"), "model_version": version,
                           "usage": meta.get("usage", {}), "text": None if answer is not None else meta.get("text", "")[:2000]})
            if answer is not None:
                break
            if attempt < FORMAT_RETRIES:
                self.res.format_retries += 1
        else:
            raise SubjectError(f"{block}: no valid answer after {FORMAT_RETRIES + 1} attempts "
                               f"({meta.get('stop_reason')}) {meta.get('text', '')[:200]}")
        self.res.calls += 1
        self.messages.append({"role": "assistant", "content": meta["text"]})
        return answer

    # --- flow ---------------------------------------------------------------------------------------------
    async def run(self) -> Result:
        t0 = time.time()
        try:
            await self._run()
        except FatalAPIError:
            raise  # wrong key, no permission: stop the run, do not flag the agent
        except SubjectError as e:
            self.res.drop_stage, self.res.error = 9, str(e)
        except Exception as e:  # anything else (network, provider, bug): flag this agent, keep the run going
            self.res.drop_stage, self.res.error = 9, f"{type(e).__name__}: {e}"[:500]
        self.res.seconds = round(time.time() - t0, 1)
        return self.res

    async def _run(self) -> None:
        instr = "InstructionsHot" if self.hot else "InstructionsCold"
        for b in ("Welcome", "Instructions", instr):
            self.show(b)

        for k in range(1, MAX_QUIZ_ATTEMPTS + 1):
            ans = await self.ask(f"QuizQ{k}", self._quiz_keys(k), self._quiz_schema(k))
            ok = self._quiz_correct(ans)
            self.res.quiz_attempts = k
            self.res.quiz_answers.append({**ans, "correct": ok})
            if ok:
                self.show("Start")
                break
            if k == MAX_QUIZ_ATTEMPTS:
                self.show("QuizNo")
                self.res.drop_stage = 2
                return
            self.show("Instructions2")
            self.show(instr)

        for r in range(1, N_ROUNDS + 1):
            trust = self.seq.choices[r - 1] == "IN"
            choice = None
            if self.hot and not trust:
                self.show(f"HotQuestion{r}OUT")
            else:
                block = f"HotQuestion{r}IN" if self.hot else f"ColdQuestion{r}"
                tag = f"HotQ{r}" if self.hot else f"ColdQ{r}"
                ans = await self.ask(block, {tag: "choice"}, self._choice_schema(block, tag))
                choice = ans["choice"]
            self.show(f"Result{r}.1" if not trust else f"Result{r}.2" if choice == "LEFT" else f"Result{r}.3")
            self.res.rounds.append({
                "round": r, "p1trust": int(trust), "choice": choice,
                "reci": None if choice is None else int(choice == "LEFT"),
                "reason": ans.get("reason") if choice is not None and self.explain else None,
            })

        self.show("Payment")
        q = self.m.block("Questionnaire")
        keys = {t: k for t, k in QUESTIONNAIRE_KEYS.items() if any(x.tag == t for x in q.questions)}
        self.res.questionnaire = await self.ask("Questionnaire", keys, _questionnaire_schema(q, keys))
        self.res.completed = True
        try:
            self.res.debrief = await self.ask("Debrief", {}, _object({k: _prop(t, e, d) for k, (t, e, d)
                                                                       in DEBRIEF_SCHEMA_PROPS.items()}), DEBRIEF_SCREEN)
        except SubjectError as e:
            self.res.debrief_error = str(e)

    # --- schemas ------------------------------------------------------------------------------------------
    # Each answer field carries its question's literal text as description: in Qualtrics the answer box sits
    # next to its question; here the form is separate from the screen text, so the question travels with it.
    def _choice_schema(self, block: str, tag: str) -> dict:
        q = next(x for x in self.m.block(block).questions if x.tag == tag)
        label = [line for line in q.text.splitlines() if line.strip()][-1]  # "I choose:", next to the buttons
        props = {"choice": _prop("string", list(q.choices), self._piped(label))}
        if self.explain:
            props["reason"] = {"type": "string", "description": "In one sentence, why you chose this."}
        return _object(props)

    def _quiz_keys(self, k: int) -> dict[str, str]:
        return {f"QuizQ{k}.{i}": f"q{i}" for i in range(1, 5)}

    def _quiz_schema(self, k: int) -> dict:
        qs = {x.tag: x for x in self.m.block(f"QuizQ{k}").questions}
        matrix = qs[f"QuizQ{k}.1"]
        props = {f"q1_{i}": _prop("string", list(matrix.choices), self._piped(s))
                 for i, s in enumerate(matrix.statements, 1)}
        for i in (2, 3, 4):
            q = qs[f"QuizQ{k}.{i}"]
            text = self._piped(q.text)
            if set(q.choices) == {"True", "False"}:  # a bare statement next to a box reads as an assertion
                text = f'True or false: "{text}"'
            props[f"q{i}"] = _prop("string", list(q.choices), text)
        return _object(props)

    def _piped(self, text: str) -> str:
        """Fill in Qualtrics piped fields, exactly as on the screen."""
        return text.replace("${e://Field/CRate}", self.seq.crate).replace("${e://Field/DRate}", self.seq.drate)

    def _quiz_correct(self, a: dict) -> bool:
        # Matrix rows: you IN-LEFT, type-1 OUT, you IN-RIGHT, type-1 IN-RIGHT (Fig. 1 payoffs).
        return (
            (a["q1_1"], a["q1_2"], a["q1_3"], a["q1_4"]) == ("35", "25", "50", "12")
            and a["q2"] == "False"
            and a["q3"] == ("True" if self.hot else "False")
            and a["q4"] == self.seq.crate
        )


def _prop(kind: str, enum: list | None, description: str) -> dict:
    p = {"type": kind, "description": re.sub(r"\s+", " ", description).strip()}
    if enum:
        p["enum"] = enum
    return p


def _object(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _questionnaire_schema(block, keys: dict[str, str]) -> dict:
    # Every text-entry item (age, comment) is free text, as in Qualtrics: no format is imposed on the answer.
    return _object({keys[q.tag]: _prop("string", list(q.choices) or None, q.text)
                    for q in block.questions if q.tag in keys})


def invalid(answer: dict, schema: dict) -> str:
    """Why an answer does not fit the form ('' if it does): missing or extra fields, wrong type, not an option."""
    props = schema["properties"]
    if set(answer) != set(props):
        return f"fields {sorted(set(answer) ^ set(props))}"
    for k, p in props.items():
        v = answer[k]
        if p["type"] == "string" and not isinstance(v, str):
            return f"{k} not text"
        if "enum" in p and v not in p["enum"]:
            return f"{k}={v!r} not an option"
    return ""


def parse_age(text: str) -> int | None:
    """Number written in the free-text age answer (None if there is none). '-28' -> -28: kept, flagged later."""
    m = re.search(r"-?\d+", str(text))
    return int(m.group()) if m else None
