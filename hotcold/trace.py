"""Follow ONE agent through the experiment, request by request, in the terminal. Nothing is written to runs/.

  uv run python -m hotcold.trace baseline_19                              # scripted model: free, no API call
  uv run python -m hotcold.trace baseline_19 --step                       # wait for Enter before each request
  uv run python -m hotcold.trace baseline_19 --pdb                        # Python debugger before each request
  uv run python -m hotcold.trace baseline_19 --wrong-quiz 2               # scripted: fail the quiz twice first
  uv run python -m hotcold.trace baseline_19 --persona nemotron --model deepinfra:openai/gpt-oss-120b  # real, ~US$0.001
  uv run python -m hotcold.trace baseline_19 --short --no-color > trace.txt

It runs the same code as a real run -- the same Persona, system prompt, screens, forms and Subject flow -- and only
wraps the model to print what is sent and what comes back. With --pdb the debugger stops inside that wrapper, where
`system`, `messages` (the whole conversation so far) and `schema` (the answer form) can be inspected.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time

import pandas as pd

from .llm import MODELS, ScriptedModel, cost_usd
from .materials import load
from .personas import DATASET, DATASET_LABEL
from .run import FINAL_SOURCES, load_dotenv, model_factory, select_personas
from .subject import SCREEN_SEPARATOR, Subject

DROP = {None: "completó el experimento", 2: "excluido: falló el quiz 6 veces", 9: "cortado (error técnico)"}


class Style:
    def __init__(self, color: bool):
        codes = {"bold": "1", "dim": "2", "sent": "36", "answer": "32", "warn": "33", "bad": "31"}
        for k, c in codes.items():
            setattr(self, k, (lambda s, c=c: f"\033[{c}m{s}\033[0m") if color else (lambda s: s))


class Tracer:
    """Model wrapper: prints each request (the screens, the form) and the answer, then passes it through."""

    def __init__(self, inner, model_name: str, st: Style, step: bool = False, pdb: bool = False, short: bool = False):
        self.inner, self.model_name, self.s = inner, model_name, st
        self.step, self.pdb, self.short = step, pdb, short
        self.screens: list[str] = []  # names of the screens in the current message (set by TracedSubject)
        self.n, self.cost, self.last = 0, 0.0, None

    async def respond(self, system: str, messages: list[dict], schema: dict):
        s, content = self.s, messages[-1]["content"]
        retry = content is self.last
        self.last = content
        self.n += 1
        print(s.bold(f"\n━━━ Pedido {self.n} " + "━" * 60))
        if retry:
            print(s.warn("La respuesta anterior no encajaba en el formulario: se vuelve a mandar el mismo mensaje."))
        else:
            k = sum(m["role"] == "user" for m in messages)
            print(s.dim(f"Mensaje {k} de la conversación · el modelo recibe el mensaje de sistema"
                        + (f" y los {len(messages) - 1} mensajes anteriores (sus pantallas y sus respuestas)" if k > 1 else "")))
            parts = content.split(SCREEN_SEPARATOR)
            names = self.screens if len(self.screens) == len(parts) else [f"pantalla {i + 1}" for i in range(len(parts))]
            for name, text in zip(names, parts):
                print(s.bold(f"\n▶ {name}"))
                print(s.sent(_cut(text, 500) if self.short else text))
        print(s.bold("\n▶ Formulario que tiene que llenar"))
        for k, v in schema["properties"].items():
            opts = " / ".join(map(str, v["enum"])) if "enum" in v else f"texto libre ({v.get('type', 'string')})"
            print(f"  {s.bold(k)}: {opts}")
            if v.get("description"):
                print(s.dim(f"      {_cut(v['description'], 160)}"))
        if self.step:
            input(s.dim("\n[Enter para mandar el pedido] "))
        if self.pdb:
            breakpoint()  # inspect: system, messages, schema  (c = continue, q = quit)
        t0 = time.time()
        answer, meta = await self.inner.respond(system, messages, schema)
        u = meta.get("usage", {})
        cost = cost_usd(self.model_name, u)
        self.cost += cost
        print(s.bold("\n◀ Respuesta"))
        if answer is None:
            print(s.bad(f"  (no encaja: {meta.get('stop_reason')}) {meta.get('text', '')[:300]}"))
        else:
            print(s.answer("  " + json.dumps(answer, ensure_ascii=False)))
        read = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        print(s.dim(f"  {time.time() - t0:.1f} s · {read:,} tokens leídos · {u.get('output_tokens', 0):,} escritos"
                    f" · US${cost:.5f} · versión: {meta.get('model_version')}"))
        return answer, meta


class TracedSubject(Subject):
    """The real Subject; it only tells the tracer which screens go in each message and comments on the answers."""

    def __init__(self, *a, human: dict[int, float], **k):
        super().__init__(*a, **k)
        self.human, self.names = human, []

    def show(self, block: str) -> None:
        self.names.append(block)
        super().show(block)

    async def ask(self, block, keys, schema, screen=None):
        self.model.screens, self.names = self.names + [block], []
        ans = await super().ask(block, keys, schema, screen)
        s = self.model.s
        if block.startswith("QuizQ"):
            ok = self._quiz_correct(ans)
            print((s.answer if ok else s.bad)(f"  → quiz {'correcto' if ok else 'incorrecto'}"))
        elif m := re.match(r"(?:HotQuestion|ColdQuestion)(\d+)", block):
            print(s.warn(f"  → ronda {m.group(1)}: la persona real eligió {_human(self.human.get(int(m.group(1))))}"
                         " (el agente no lo ve)"))
        return ans


def _cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n].rstrip() + " […]"


def _human(reci) -> str:
    return "—" if reci is None or pd.isna(reci) else "LEFT" if reci == 1 else "RIGHT"


def human_choices(experiment: str, real_id: int) -> dict[int, float]:
    d = pd.read_csv(DATASET, usecols=["experiment", "id", "round", "reci"])
    d = d[(d.experiment == DATASET_LABEL[experiment]) & (d.id == real_id)]
    return dict(zip(d["round"], d.reci))


async def trace(agent_id: str, persona: str = "demographic", model: str = "scripted", thinking: str = "off",
                step: bool = False, pdb: bool = False, short: bool = False, wrong_quiz: int = 0,
                color: bool = True) -> None:
    s = Style(color)
    people = {p.agent_id: p for p in select_personas(persona, 0)}
    if agent_id not in people:
        ids = sorted(people, key=lambda a: int(a.rsplit("_", 1)[1]))
        raise SystemExit(f"{agent_id} no existe. Hay {len(ids)} agentes: {ids[0]} … {ids[-1]}")
    p = people[agent_id]
    inner = ScriptedModel("random", wrong_quiz=wrong_quiz, seed=1) if model == "scripted" else model_factory(model, thinking)()
    tracer = Tracer(inner, model, s, step, pdb, short)
    human = human_choices(p.experiment, p.real_id)
    subj = TracedSubject(p, load(p.experiment), tracer, human=human)

    print(s.bold(f"Agente {agent_id}") + f" · modelo {model} · Persona {persona}")
    print(f"Persona real ({p.real_id} en hotcold_dataset): {p.gender}, {p.age} años, {p.education} · condición {p.treatment}, "
          f"tasa de confianza anunciada {p.crate}")
    print("Secuencia del otro jugador (la misma que vio la persona real): " + " ".join(subj.seq.choices))
    print(s.bold("\n━━━ Mensaje de sistema (va en todos los pedidos) " + "━" * 30))
    print(s.sent(subj.system))

    res = await subj.run()

    print(s.bold("\n━━━ Resumen " + "━" * 66))
    quit_pdb = bool(res.error) and res.error.startswith("BdbQuit")
    print(f"{'cortado en el debugger' if quit_pdb else DROP.get(res.drop_stage, res.drop_stage)} · intentos de quiz: {res.quiz_attempts} · pedidos: {res.requests}"
          f" (reintentos por formato: {res.format_retries}) · {res.seconds:.0f} s · US${tracer.cost:.4f}")
    if quit_pdb:
        print(s.warn("Se cerró el debugger: el agente quedó cortado ahí (en una corrida real no pasa)."))
    elif res.error:
        print(s.bad(f"error: {res.error}"))
    if res.rounds:
        print(s.bold("\nRonda  otro   agente  persona real"))
        for r in res.rounds:
            same = "" if r["choice"] is None else " ✓" if r["choice"] == _human(human.get(r["round"])) else ""
            print(f"{r['round']:>5}  {'IN ' if r['p1trust'] else 'OUT'}   {r['choice'] or '—':<6}  "
                  f"{_human(human.get(r['round']))}{same}")
        dec = [r for r in res.rounds if r["reci"] is not None]
        print(f"Devolvió la confianza en {sum(r['reci'] for r in dec)} de {len(dec)} decisiones.")
    if res.questionnaire:
        print(s.bold("\nCuestionario: ") + f"edad {res.questionnaire.get('age')!r} (real {p.age}), "
              f"género {res.questionnaire.get('gender')} (real {p.gender}), "
              f"educación {res.questionnaire.get('education')} (real {p.education})")
    if res.debrief:
        print(s.bold("Debrief: ") + json.dumps(res.debrief, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent", nargs="?", default="baseline_19", help="agent id, e.g. baseline_19")
    ap.add_argument("--persona", default="demographic", choices=FINAL_SOURCES)
    ap.add_argument("--model", default="scripted", choices=["scripted", *MODELS])
    ap.add_argument("--thinking", choices=["off", "on"], default="off")
    ap.add_argument("--step", action="store_true", help="wait for Enter before each request")
    ap.add_argument("--pdb", action="store_true", help="open the Python debugger before each request")
    ap.add_argument("--short", action="store_true", help="cut each screen to 500 characters")
    ap.add_argument("--wrong-quiz", type=int, default=0, help="scripted model only: fail the quiz this many times first")
    ap.add_argument("--no-color", action="store_true")
    a = ap.parse_args()
    if a.model != "scripted":
        load_dotenv()
    asyncio.run(trace(a.agent, a.persona, a.model, a.thinking, a.step, a.pdb, a.short, a.wrong_quiz,
                      color=not a.no_color and sys.stdout.isatty()))


if __name__ == "__main__":
    main()
