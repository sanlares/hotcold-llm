import asyncio
import json
import re

import pandas as pd
import pytest

from hotcold.llm import ScriptedModel
from hotcold.materials import N_ROUNDS, QSF, clean, load
from hotcold.personas import DATASET, build_personas, load_participants
from hotcold.subject import Subject


@pytest.fixture(scope="module")
def m():
    return load("baseline")


@pytest.fixture(scope="module")
def personas():
    return build_personas("baseline")


def run(p, m, model):
    s = Subject(p, m, model)
    return s, asyncio.run(s.run())


def first(personas, treatment, crate="28%"):
    return next(p for p in personas if p.treatment == treatment and p.crate == crate)


def test_sequences(m):
    assert len(m.sequences) == 80
    for s in m.sequences.values():
        assert len(s.choices) == N_ROUNDS and s.choices[0] == "IN"  # round 1 is always a trusting first mover
    counts = pd.Series([(s.treatment, s.crate) for s in m.sequences.values()]).value_counts()
    assert (counts == 20).all()


def test_screens_are_verbatim(m):
    """Every rendered round screen equals the cleaned Qualtrics question text (only CRate/DRate piped in)."""
    survey = json.loads(QSF["baseline"].read_text())
    raw = {e["Payload"]["DataExportTag"]: e["Payload"]["QuestionText"] for e in survey["SurveyElements"]
           if e["Element"] == "SQ"}
    for r in (1, 7, 20):
        for block, tag in [(f"HotQuestion{r}OUT", f"HotOUT{r}"), (f"Result{r}.3", f"Result{r}.3")]:
            expected = clean(raw[tag]).replace("${e://Field/CRate}", "28%").replace("${e://Field/DRate}", "72%")
            assert m.block(block).render("28%", "72%") == expected


def test_personas_match_real_people(personas):
    people = load_participants("baseline").set_index("real_id")
    assert len(personas) == 396
    assert len({p.agent_id for p in personas}) == len({p.backstory() for p in personas}) == 396
    ds = set(pd.read_csv(DATASET, usecols=["id"]).id)
    for p in personas:
        r = people.loc[p.real_id]
        assert p.real_id in ds
        assert (p.age, p.gender, p.education, p.group) == (int(r.Age), r.Gender, r.Education, int(r.Group))
        assert p.agent_id.split("_")[1] == p.real_id.rsplit("_", 1)[1]


def test_personas_are_reproducible_and_outcome_free(personas):
    again = build_personas("baseline")
    assert [p.backstory() for p in personas] == [p.backstory() for p in again]
    banned = re.compile(r"generous|selfish|trust|fair|kind|honest|greedy|reciproc|altruis|charit|volunteer|"
                        r"gambl|poker|religio|political views|vote|personality|money", re.I)
    for p in personas:
        assert not banned.search(p.backstory()), p.backstory()


def test_hot_asks_only_on_in(m, personas):
    p = first(personas, "Hot")
    seq = m.sequences[p.group]
    s, res = run(p, m, ScriptedModel("left"))
    n_in = seq.choices.count("IN")
    assert res.completed and res.quiz_attempts == 1
    assert res.calls == 1 + n_in + 2  # quiz + one decision per IN + questionnaire + debrief
    assert [x["p1trust"] for x in res.rounds] == [int(c == "IN") for c in seq.choices]
    assert all((x["reci"] == 1) == (x["p1trust"] == 1) for x in res.rounds)


def test_cold_asks_every_round(m, personas):
    p = first(personas, "Cold", "69%")
    s, res = run(p, m, ScriptedModel("right"))
    assert res.completed and res.calls == 1 + N_ROUNDS + 2
    assert all(x["reci"] == 0 for x in res.rounds)
    # the result shown after a decision matches the type-1 choice and own choice
    seq = m.sequences[p.group]
    r_out = seq.choices.index("OUT") + 1
    nxt = next(msg["content"] for msg in s.messages if f"Round {r_out} – Result" in msg["content"])
    assert f"in round {r_out} chose OUT." in nxt


def test_quiz_retries_and_exclusion(m, personas):
    p = first(personas, "Hot")
    s, res = run(p, m, ScriptedModel("left", wrong_quiz=2))
    assert res.completed and res.quiz_attempts == 3
    assert "Some of your answers are not correct" in s.messages[2]["content"]
    assert "It is your third chance" in s.messages[4]["content"]

    s, res = run(p, m, ScriptedModel("left", wrong_quiz=6))
    assert not res.completed and res.drop_stage == 2 and res.quiz_attempts == 6 and not res.rounds


def test_text_entry_fields_labelled(m):
    from hotcold.subject import QUESTIONNAIRE_KEYS
    text = m.block("Questionnaire").render("28%", "72%", QUESTIONNAIRE_KEYS)
    assert "(answer field: age)" in text and "(answer field: comment)" in text


def test_backstory_states_real_education_and_gender(personas):
    from hotcold.personas import EDUCATION_LINE
    for p in personas:
        b = p.backstory()
        assert EDUCATION_LINE[p.education] in b
        if p.gender == "I would rather not say":
            assert "prefer not to disclose your gender" in b


def test_rich_personas_are_the_pilot_agents_and_optional(personas):
    from hotcold.personas import add_rich
    from hotcold.run import sample
    basic = {p.agent_id: p.backstory() for p in personas}
    rich = add_rich(build_personas("baseline"))
    assert {p.agent_id for p in rich} == {p.agent_id for p in sample(personas, 5, 1)}
    for p in rich:
        b = p.backstory()
        assert b.startswith(basic[p.agent_id]) and len(b) > len(basic[p.agent_id]) + 500
    assert all(not p.rich for p in personas)  # basic mode untouched


@pytest.mark.parametrize("src", ["prism", "nemotron", "twin-summary", "twin-narrative", "twin-demographic"])
def test_external_sources_keep_pilot_sequences_and_hide_games(personas, src):
    from hotcold import sources
    from hotcold.run import sample
    if not (sources.EXT / "prism/survey.jsonl").exists():
        pytest.skip("external data not downloaded")
    base = sample(personas, 5, 1)
    built = sources.build(src, base)
    assert [(p.group, p.treatment, p.crate) for p in built] == [(p.group, p.treatment, p.crate) for p in base]
    assert len({p.source_ref for p in built}) == 20
    for p in built:
        text = p.backstory().lower()
        assert "trust game" not in text and "dictator" not in text and "ultimatum" not in text
        assert "(anonymous) person" not in text


def test_twin_qa_has_no_games():
    from hotcold import sources
    if not (sources.EXT / "twin/persona_chunk_001.parquet").exists():
        pytest.skip("external data not downloaded")
    for pid in sources.twin_sample(20):
        q = sources.twin_qa(pid)
        assert "tripled" not in q and "(anonymous) person" not in q and "keep for yourself" not in q


# --- final design: Personas ------------------------------------------------------------------------------------
def test_demographic_persona_has_only_real_data(personas):
    from hotcold.personas import demographic_personas
    demo = demographic_personas(personas)
    for p, d in zip(personas, demo):
        b = d.backstory()
        assert p.name not in b and p.hometown not in b and p.field_of_study not in b
        assert f"aged {p.age}" in b and "student" in b and "UK" in b
        assert d.name == "" and d.hobbies == [] and d.source == "demographic"
    assert len({d.backstory() for d in demo}) < len(demo)  # same demographics -> same text: nothing invented


def test_final_personas_say_student_once():
    from hotcold.run import select_personas
    for src in ("demographic", "nemotron"):
        for p in select_personas(src, 0):
            facts = p.backstory().split("\n\n")[0]  # the real-data sentences (Nemotron adds its narrative after them)
            assert facts.count("student") == 1 and "undergraduate" not in facts, facts


def test_nemotron_for_all_agents(personas):
    from hotcold import sources
    from hotcold.run import sample
    if not sources.NEMO_FILE.exists():
        pytest.skip("external data not downloaded")
    full = sources.nemotron_personas(personas)
    assert len({p.source_ref for p in full}) == 396  # each Nemotron persona used once
    assert all(p.match_student and p.match_age_diff <= 5 for p in full)
    pool = sources.nemotron_pool().set_index("uuid")
    assert pool.loc[[p.source_ref for p in full]].student.all()
    sub = sources.nemotron_personas(sample(personas, 5, 1))  # a pilot gets the same match as the full run
    by_id = {p.agent_id: p.source_ref for p in full}
    assert all(by_id[p.agent_id] == p.source_ref for p in sub)
    assert [p.backstory() for p in full] == [p.backstory() for p in sources.nemotron_personas(build_personas("baseline"))]
    for p in full:
        b = p.backstory()
        assert f"aged {p.age}" in b and "trust game" not in b.lower()


# --- final design: prompt ------------------------------------------------------------------------------------------
def test_answer_fields_carry_their_question(m, personas):
    s = Subject(personas[0], m, ScriptedModel())
    quiz = s._quiz_schema(1)["properties"]
    assert "chooses IN and you choose RIGHT" in quiz["q1_4"]["description"]
    assert "same type-1 participant" in quiz["q2"]["description"]
    from hotcold.subject import QUESTIONNAIRE_KEYS, _questionnaire_schema
    q = _questionnaire_schema(m.block("Questionnaire"), QUESTIONNAIRE_KEYS)["properties"]
    assert q["age"] == {"type": "string", "description": "What is your age?"}  # free text, as in Qualtrics


def test_debrief_comes_last(m, personas):
    from hotcold.subject import DEBRIEF_SCREEN
    s, res = run(first(personas, "Cold"), m, ScriptedModel("left"))
    users = [x["content"] for x in s.messages if x["role"] == "user"]
    assert users[-1] == DEBRIEF_SCREEN and "What is your age?" in users[-2]
    assert set(res.debrief) == {"how_decided", "seen_before", "seen_which"}


# --- final design: errors, resume, limits, records -----------------------------------------------------------------
def _run_agents(ps, factory, outdir, limit=4, budget=None):
    from hotcold.run import run_agents
    return asyncio.run(run_agents(ps, factory, "scripted", outdir, asyncio.Semaphore(limit), budget))


def test_technical_failure_is_retried_then_flagged(m, personas):
    s, res = run(first(personas, "Hot"), m, ScriptedModel("left", bad_first=2))
    assert res.completed and res.format_retries == 2 and res.requests == res.calls + 2
    s, res = run(first(personas, "Hot"), m, ScriptedModel("left", bad_first=3))
    assert not res.completed and res.drop_stage == 9 and "QuizQ1" in res.error


def test_one_agent_crashing_does_not_stop_the_run(personas, tmp_path):
    from hotcold.llm import FatalAPIError
    ps = personas[:6]
    boom = iter([True, False, False, True, False, False])
    st = _run_agents(ps, lambda: ScriptedModel(raise_at=(3, ConnectionError("network down")) if next(boom) else None),
                     tmp_path)
    lines = [json.loads(x) for x in (tmp_path / "results.jsonl").open()]
    assert st.done == 6 and st.errors == 2 and sum(r["completed"] for r in lines) == 4
    assert all("ConnectionError" in r["error"] for r in lines if r["drop_stage"] == 9)
    # a wrong key stops the run instead of flagging every agent
    st = _run_agents(personas[6:12], lambda: ScriptedModel(raise_at=(1, FatalAPIError("401"))), tmp_path / "x")
    assert st.stopped.startswith("fatal") and st.done == 0


def test_resume_does_not_repeat_agents(personas, tmp_path):
    from hotcold.run import Budget, drop_errors
    ps = personas[:12]
    st = _run_agents(ps[:5], lambda: ScriptedModel(), tmp_path)
    st = _run_agents(ps, lambda: ScriptedModel(), tmp_path)
    ids = [json.loads(x)["agent_id"] for x in (tmp_path / "results.jsonl").open()]
    assert st.done == 7 and sorted(ids) == sorted(p.agent_id for p in ps)
    # spending limit: nothing new starts once it is reached
    st = _run_agents(personas[12:20], lambda: ScriptedModel(), tmp_path / "b", limit=1, budget=Budget(limit=0.0))
    assert st.done == 0 and st.stopped.startswith("spending limit")
    # --retry-errors moves technical errors aside so they run again
    _run_agents(personas[20:22], lambda: ScriptedModel(bad_first=9), tmp_path / "c")
    assert drop_errors(tmp_path / "c") == 2 and (tmp_path / "c" / "results.jsonl").read_text() == ""


def test_provider_limit_is_respected(personas, tmp_path):
    active = {"now": 0, "max": 0}

    class Counting(ScriptedModel):
        async def respond(self, *a):
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            await asyncio.sleep(0.001)
            active["now"] -= 1
            return await super().respond(*a)

    _run_agents(personas[:9], lambda: Counting(), tmp_path, limit=3)
    assert active["max"] == 3


def test_odd_answers_are_kept_and_flagged(personas, tmp_path):
    from hotcold.personas import demographic_personas
    from hotcold.run import save
    ps = demographic_personas(personas[:2])
    _run_agents(ps, lambda: ScriptedModel(age="-28"), tmp_path)
    panel, subj = save(tmp_path, ps)
    assert (subj.q_age == "-28").all() and (subj.chk_age_number == -28).all()
    assert not subj.chk_age_plausible.any() and not subj.chk_age_matches.any()
    calls = [json.loads(x) for x in (tmp_path / "calls.jsonl").open()]
    assert len(calls) == subj.requests.sum() and all(c["ok"] for c in calls)


def test_manifest_records_versions(tmp_path):
    from hotcold.manifest import write_manifest
    write_manifest(tmp_path, {"model": "anthropic:claude-haiku-5-5", "persona": "demographic"})
    write_manifest(tmp_path, {"model": "anthropic:claude-haiku-5-5", "persona": "demographic"})
    m = json.loads((tmp_path / "manifest.json").read_text())
    assert len(m) == 2  # a resumed run keeps the earlier entry
    for k in ("code_sha256", "libraries", "data", "system_template", "debrief_screen", "request_settings", "python"):
        assert m[-1][k], k
    assert m[-1]["libraries"]["langchain"] and len(m[-1]["data"]["qsf"]["sha256"]) == 64


def test_input_audit_catches_planted_problems(m, personas):
    import pandas as pd
    from dataclasses import replace
    from hotcold.audit_inputs import hard_checks
    from hotcold.personas import DATASET, demographic_personas, load_participants
    raw = load_participants("baseline").set_index("real_id")
    ds = pd.read_csv(DATASET, usecols=["experiment", "id", "round", "p1trust"])
    ds = ds[ds.experiment == "Baseline experiment"].sort_values(["id", "round"])
    seqs = {i: g.p1trust.fillna(-1).astype(int).tolist() for i, g in ds.groupby("id")}
    ok = demographic_personas(personas[:3])
    assert hard_checks("demo", ok, m, raw, seqs) == []
    bad = [replace(ok[0], override="You are nan, aged 20."), replace(ok[1], age=99),
           replace(ok[2], override="Your rate is ${e://Field/CRate} aged " + str(ok[2].age))]
    found = hard_checks("demo", bad, m, raw, seqs)
    assert any("'nan'" in x for x in found) and any("demographics differ" in x for x in found)
    assert any("'${'" in x for x in found)


def test_analysis_reproduces_paper_table2():
    from hotcold.analysis import validate
    assert validate() == []


# --- after the independent review ---------------------------------------------------------------------------------
def test_anthropic_cache_writes_are_counted():
    from hotcold.llm import _usage, cost_usd
    # what langchain-anthropic 1.7 returns: writes under ephemeral_5m_input_tokens, cache_creation set to 0
    u = _usage({"input_tokens": 1000, "output_tokens": 10,
                "input_token_details": {"cache_read": 600, "cache_creation": 0, "ephemeral_5m_input_tokens": 300}})
    assert u == {"input_tokens": 100, "cache_creation_input_tokens": 300, "cache_read_input_tokens": 600, "output_tokens": 10}
    assert cost_usd("anthropic:claude-haiku-5-5", u) > cost_usd("anthropic:claude-haiku-5-5", {**u, "cache_creation_input_tokens": 0, "input_tokens": 400})


def test_debrief_failure_keeps_a_completed_session(m, personas):
    class FailsLast(ScriptedModel):
        async def respond(self, system, messages, schema):
            if "how_decided" in schema["properties"]:
                return None, {"stop_reason": "length", "text": "", "usage": {}}
            return await super().respond(system, messages, schema)
    s, res = run(first(personas, "Cold"), m, FailsLast())
    assert res.completed and res.drop_stage is None and res.debrief_error and not res.debrief


def test_cut_last_line_is_repaired_on_resume(personas, tmp_path):
    from hotcold.run import done_ids
    _run_agents(personas[:3], lambda: ScriptedModel(), tmp_path)
    with (tmp_path / "results.jsonl").open("a") as f:
        f.write('{"agent_id": "baseline_99", "rou')  # process killed while writing
    assert len(done_ids(tmp_path)) == 3
    st = _run_agents(personas[:4], lambda: ScriptedModel(), tmp_path)
    assert st.done == 1 and len(done_ids(tmp_path)) == 4


def test_batch_limit_is_shared_between_runs(personas, tmp_path):
    from hotcold.batch import run_batch
    from hotcold.run import Budget
    active = {"now": 0, "max": 0}

    class Counting(ScriptedModel):
        async def respond(self, *a):
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            await asyncio.sleep(0.001)
            active["now"] -= 1
            return await super().respond(*a)

    combos = [{"name": f"r{i}", "personas": personas[i * 4:(i + 1) * 4], "outdir": tmp_path / f"r{i}",
               "make_model": lambda: Counting(), "cfg": {"dry_run": False, "model": "deepinfra:x", "explain": False}}
              for i in range(3)]
    out = asyncio.run(run_batch(combos, {"deepinfra": 2}, Budget(), tmp_path))
    assert active["max"] == 2 and len(out) == 3


def test_analysis_uses_completed_agents_and_paired_humans(personas, tmp_path):
    from hotcold.analysis import load_runs, with_paired_humans, humans
    from hotcold.personas import demographic_personas
    from hotcold.run import prepare_run, save
    ps = demographic_personas(personas[:8])
    out = tmp_path / "run"
    prepare_run(out, {"model": "scripted", "persona": "demographic"}, ps)
    _run_agents(ps[:4], lambda: ScriptedModel(), out)
    _run_agents(ps[4:], lambda: ScriptedModel(raise_at=(5, ConnectionError("x"))), out)  # cut in round ~3
    save(out, ps)
    panel, subjects = load_runs([out])
    assert set(panel.agent_id) == {p.agent_id for p in ps[:4]}  # incomplete agents do not enter
    allp = with_paired_humans(humans(), panel)
    paired = allp[allp.source.str.endswith("paired humans")]
    assert set(paired.real_id) == {p.real_id for p in ps[:4]} and paired.reci.notna().any()


def test_trace_follows_one_agent_without_saving(capsys, tmp_path, monkeypatch):
    from hotcold import trace
    monkeypatch.chdir(tmp_path)
    asyncio.run(trace.trace("baseline_19", wrong_quiz=1, short=True, color=False))
    out = capsys.readouterr().out
    assert "Mensaje de sistema" in out and "quiz incorrecto" in out and "quiz correcto" in out
    assert out.count("━━━ Pedido") == 9 and "completó el experimento" in out
    assert "la persona real eligió" in out and not any(tmp_path.iterdir())


def test_knowledge_probe_asks_each_title_apart():
    from hotcold.probe_knowledge import QUESTIONS
    pub, wp = QUESTIONS["published"][0], QUESTIONS["wp2024"][0]
    assert "Hot-cold reciprocation gaps" in pub and "surprising" not in pub and "19248" not in pub
    assert "A surprising hot-cold reciprocation gap" in wp and "Experimental Economics" not in wp
    assert "Baseline" not in wp and "LEFT" not in wp  # no description of the game: only the title is asked


def test_spend_limit_stops_the_run_instead_of_flagging_agents():
    from hotcold.llm import is_fatal
    msg = "Error code: 429 - Your organization has reached its configured enforced spend limit."
    assert is_fatal(Exception(msg)) and not is_fatal(Exception("Error code: 429 - Rate limit reached"))


def test_exploratory_parsing_and_measures():
    from hotcold.exploratory import history_table, pounds, scale, switch_rate
    assert scale("0 (Not at all tempted)") == 0 and scale(7) == 7 and scale("10 (describe me perfectly)") == 10
    assert pounds("No present") == 0 and pounds("The present worth 15 Pounds") == 15
    d = pd.DataFrame({"agent_id": ["a"] * 4 + ["b"] * 2, "round": [1, 2, 3, 4, 1, 2], "reci": [1, 0, 0, 1, 1, 1]})
    assert switch_rate(d) == 2 / 4  # a changes twice in 3 pairs, b never in 1
    # 40 Cold agents; type-1 chooses IN in odd rounds, OUT in even ones; the agent chooses LEFT only after an OUT
    rows = [{"source": "x", "agent_id": f"g{i}", "round": r, "hot": 0, "p1trust": r % 2,
             "reci": float(r % 2 == 1 and r > 1)} for i in range(40) for r in range(1, 21)]
    t = history_table(pd.DataFrame(rows)).iloc[0]
    assert t["Cold: after IN %"] == "0" and t["Cold: after OUT %"] == "100" and t["Hot: after IN %"] == "—"


def test_exploratory_runs_on_a_scripted_run(personas, tmp_path):
    from hotcold.exploratory import explore
    from hotcold.personas import demographic_personas
    from hotcold.run import prepare_run, save
    ps = demographic_personas(personas[:12])
    out = tmp_path / "run"
    prepare_run(out, {"model": "scripted", "persona": "demographic"}, ps)
    _run_agents(ps, lambda: ScriptedModel(), out)
    save(out, ps)
    text = explore([out], tmp_path / "analysis")
    assert all(f"## X{i}." in text for i in range(1, 12)) and (tmp_path / "analysis" / "fig_overview.png").exists()
    assert "a cell under 30 agents" in text  # 12 agents: the formal test is not run


def test_persona_average_weighs_models_equally_and_drops_thin_ones():
    from hotcold.analysis import CELLS
    from hotcold.exploratory import HUMANS, averaged_models, persona_average_table
    rows = []

    def add(model, persona, cell, n, value):
        src = HUMANS if model is None else f"{model} · {persona}"
        rows.extend({"source": src, "model": model, "persona": persona, "treat": cell, "agent_id": f"{src}{cell}{i}",
                     "real_id": i, "round": r, "reci": value, "hot": int(cell.startswith("Hot"))}
                    for i in range(n) for r in (1, 19, 20))
    for c in CELLS:
        add(None, None, c, 40, 0.5)
        for p in ("demographic", "nemotron"):
            add("a", p, c, 40, 1.0)
            add("b", p, c, 30, 0.0)
            add("thin", p, c, 300 if c.startswith("Cold") else 2, 0.0)  # almost no agents in Hot, like gpt-5-nano
    allp = pd.DataFrame(rows)
    assert averaged_models(allp) == ["a", "b"]
    t = persona_average_table(allp)
    row = t[(t.window == "rounds 1-20") & t.group.str.startswith("demographic")].iloc[0]
    assert row["Cold-Low"] == "50 (0–100)"  # 40 agents at 100% and 30 at 0%: 50, not the pooled 57


def test_paper_figure2_bars_are_cell_rates_with_statas_interval():
    """fig2.do: reg reci i.treat + margins. Round 1 (classical): rate ± t(n−4) · s/√n_cell; read off the paper's Fig. 2,
    rounds 19-20: Hot-Low ≈ .49 [.35, .63], Cold-Low ≈ .29 [.21, .37]."""
    from hotcold.analysis import decisions, humans
    from hotcold.exploratory import cell_margins, t_crit
    assert abs(t_crit(10) - 2.2281) < 1e-3 and abs(t_crit(1e9) - 1.95996) < 1e-4
    d = decisions(humans(), "round 1")
    m = cell_margins(d, cluster=False)
    means = d.groupby("treat").reci.mean()
    s2 = ((d.reci - d.treat.map(means)) ** 2).sum() / (len(d) - 4)
    for c, x in d.groupby("treat"):
        assert abs(m.loc[c, "rate"] - means[c]) < 1e-12
        assert abs(m.loc[c, "hi"] - means[c] - t_crit(len(d) - 4) * (s2 / len(x)) ** 0.5) < 1e-9
    late = cell_margins(decisions(humans(), "rounds 19-20"), cluster=True).round(2)
    assert late.loc["Hot-Low"].tolist() == [0.49, 0.35, 0.63] and late.loc["Cold-Low"].tolist() == [0.29, 0.21, 0.37]


def test_formal_surprise_test_reproduces_the_paper():
    """Sec. 4.1: Hot 0.103 (P = 0.037); Hot in Low 0.177 (P = 0.030), in High 0.065 (P = 0.289); Hot×High P = 0.275."""
    from hotcold.analysis import decisions, humans
    from hotcold.exploratory import t_pvalue, table2
    assert abs(t_pvalue(2.228139, 10) - 0.05) < 1e-5 and abs(t_pvalue(1.959964, 1e9) - 0.05) < 1e-5
    assert t_pvalue(0, 30) == 1 and t_pvalue(float("inf"), 30) == 0
    est, n = table2(decisions(humans(), "rounds 19-20"), cluster=True)
    assert n == 579
    paper = {"Hot": (0.103, 0.037), "Hot in Low": (0.177, 0.030), "Hot in High": (0.065, 0.289), "Hot×High": (-0.112, 0.275)}
    for k, (b, p) in paper.items():
        assert abs(est[k][0] - b) < 0.0015 and abs(est[k][2] - p) < 0.0015, k
