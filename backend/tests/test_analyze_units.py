"""Unit tests for Layer 4 static-analysis checks (no LLM, no DB)."""

from __future__ import annotations

from app.analyze.registry import all_checks
from app.analyze.service import Analyzer
from app.schemas.finding import CheckTier, Severity
from app.schemas.ir_sop import (
    SLA,
    ArtifactRef,
    CompareCondition,
    Decision,
    DecisionBranch,
    ModalVerb,
    Process,
    ReviewStatus,
    RoleRef,
    SopIR,
    Step,
    SymbolTable,
    SystemRef,
    TimeUnit,
    Transition,
    Trigger,
    TypedValue,
    VagueCondition,
    ValueType,
)

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


_DEFAULT_TRIGGER = Trigger(description="incident reported")


def _ir(
    *,
    steps: list[Step] | None = None,
    decisions: list[Decision] | None = None,
    transitions: list[Transition] | None = None,
    roles: list[RoleRef] | None = None,
    artifacts: list[ArtifactRef] | None = None,
    systems: list[SystemRef] | None = None,
    trigger: Trigger | None = _DEFAULT_TRIGGER,
) -> SopIR:
    symbols = SymbolTable(
        roles=roles or [RoleRef(id="agent", name="Agent")],
        artifacts=artifacts or [ArtifactRef(id="form", name="Form")],
        systems=systems or [SystemRef(id="crm", name="CRM")],
    )
    proc = Process(
        id="p01",
        name="Test Process",
        document_id="doc1",
        steps=steps
        or [Step(id="s01", action="log it", actor_role_id="agent", modal=ModalVerb.SHALL)],
        decisions=decisions or [],
        transitions=transitions or [],
        trigger=trigger,
    )
    return SopIR(
        run_id="run1",
        document_ids=["doc1"],
        symbols=symbols,
        processes=[proc],
        review_status=ReviewStatus.APPROVED,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_all_checks_returns_non_empty_list():
    checks = all_checks()
    assert len(checks) >= 6
    prefixes = {c.code_prefix for c in checks}
    assert {"ST", "RS", "DF", "TM", "LG"} <= prefixes


# ---------------------------------------------------------------------------
# Structural checks (ST)
# ---------------------------------------------------------------------------


def test_st006_missing_trigger():
    ir = _ir(trigger=None)
    checks = {c.code_prefix: c for c in all_checks()}
    diags = checks["ST"].fn(ir, None)
    codes = [d.code for d in diags]
    assert "ST006" in codes


def test_no_st006_when_trigger_present():
    ir = _ir(trigger=Trigger(description="incident_reported"))
    checks = {c.code_prefix: c for c in all_checks()}
    diags = checks["ST"].fn(ir, None)
    assert "ST006" not in [d.code for d in diags]


def test_st001_unreachable_step():
    steps = [
        Step(id="s01", action="first", actor_role_id="agent", modal=ModalVerb.SHALL),
        Step(id="s02", action="orphan", actor_role_id="agent", modal=ModalVerb.SHALL),
    ]
    transitions = [Transition(from_id="s01", to_id="END")]
    ir = _ir(steps=steps, transitions=transitions)
    from app.analyze.checks.structural import structural_checks

    diags = structural_checks(ir, None)
    assert any(d.code == "ST001" and d.step_id == "s02" for d in diags)


def test_st002_dead_end():
    steps = [Step(id="s01", action="dead end", actor_role_id="agent", modal=ModalVerb.SHALL)]
    ir = _ir(steps=steps, transitions=[])
    from app.analyze.checks.structural import structural_checks

    diags = structural_checks(ir, None)
    assert any(d.code == "ST002" for d in diags)


# ---------------------------------------------------------------------------
# Responsibility checks (RS)
# ---------------------------------------------------------------------------


def test_rs001_no_actor_on_shall_step():
    steps = [Step(id="s01", action="verify", modal=ModalVerb.SHALL)]
    ir = _ir(steps=steps)
    from app.analyze.checks.responsibility import responsibility_checks

    diags = responsibility_checks(ir, None)
    assert any(d.code == "RS001" and d.severity == Severity.ERROR for d in diags)


def test_rs001_no_actor_on_may_step_is_warning():
    steps = [Step(id="s01", action="log", modal=ModalVerb.MAY)]
    ir = _ir(steps=steps)
    from app.analyze.checks.responsibility import responsibility_checks

    diags = responsibility_checks(ir, None)
    rs = [d for d in diags if d.code == "RS001"]
    assert rs and rs[0].severity == Severity.WARNING


def test_rs002_vague_actor():
    steps = [
        Step(id="s01", action="log", modal=ModalVerb.SHALL, actor_raw="the team")
    ]
    ir = _ir(steps=steps)
    from app.analyze.checks.responsibility import responsibility_checks

    diags = responsibility_checks(ir, None)
    assert any(d.code == "RS002" for d in diags)


def test_no_rs001_when_actor_present():
    steps = [
        Step(id="s01", action="log", modal=ModalVerb.SHALL, actor_role_id="agent")
    ]
    ir = _ir(steps=steps)
    from app.analyze.checks.responsibility import responsibility_checks

    diags = responsibility_checks(ir, None)
    assert not any(d.code in ("RS001", "RS002") for d in diags)


# ---------------------------------------------------------------------------
# Data-flow checks (DF)
# ---------------------------------------------------------------------------


def test_df001_use_before_define():
    steps = [
        Step(id="s01", action="use form", inputs=["form"], modal=ModalVerb.SHALL),
        Step(id="s02", action="produce form", outputs=["form"], modal=ModalVerb.SHALL),
    ]
    ir = _ir(steps=steps)
    from app.analyze.checks.dataflow import dataflow_checks

    diags = dataflow_checks(ir, None)
    assert any(d.code == "DF001" and d.step_id == "s01" for d in diags)


def test_df002_undefined_artifact():
    steps = [Step(id="s01", action="use ghost", inputs=["ghost_form"], modal=ModalVerb.SHALL)]
    ir = _ir(steps=steps)
    from app.analyze.checks.dataflow import dataflow_checks

    diags = dataflow_checks(ir, None)
    assert any(d.code == "DF002" for d in diags)


def test_df003_produced_never_consumed():
    steps = [Step(id="s01", action="produce form", outputs=["form"], modal=ModalVerb.SHALL)]
    ir = _ir(steps=steps)
    from app.analyze.checks.dataflow import dataflow_checks

    diags = dataflow_checks(ir, None)
    assert any(d.code == "DF003" for d in diags)


def test_no_df_errors_for_clean_flow():
    steps = [
        Step(id="s01", action="produce form", outputs=["form"], modal=ModalVerb.SHALL),
        Step(id="s02", action="use form", inputs=["form"], modal=ModalVerb.SHALL),
    ]
    ir = _ir(steps=steps)
    from app.analyze.checks.dataflow import dataflow_checks

    diags = dataflow_checks(ir, None)
    assert not any(d.code in ("DF001", "DF002") for d in diags)


# ---------------------------------------------------------------------------
# Temporal checks (TM)
# ---------------------------------------------------------------------------


def test_tm001_missing_sla_on_shall_step():
    steps = [Step(id="s01", action="log", modal=ModalVerb.SHALL, sla=None)]
    ir = _ir(steps=steps)
    from app.analyze.checks.temporal import temporal_checks

    diags = temporal_checks(ir, None)
    assert any(d.code == "TM001" for d in diags)


def test_no_tm001_when_sla_present():
    sla = SLA(max_duration=4, unit=TimeUnit.HOURS)
    steps = [Step(id="s01", action="log", modal=ModalVerb.SHALL, sla=sla)]
    ir = _ir(steps=steps)
    from app.analyze.checks.temporal import temporal_checks

    diags = temporal_checks(ir, None)
    assert not any(d.code == "TM001" for d in diags)


def test_tm003_vague_sla():
    sla = SLA(max_duration=0, unit=TimeUnit.HOURS, vague=True, vague_text="promptly")
    steps = [Step(id="s01", action="log", modal=ModalVerb.SHALL, sla=sla)]
    ir = _ir(steps=steps)
    from app.analyze.checks.temporal import temporal_checks

    diags = temporal_checks(ir, None)
    assert any(d.code == "TM003" for d in diags)


def test_tm003_vague_action_text():
    steps = [Step(id="s01", action="resolve asap", modal=ModalVerb.SHALL)]
    ir = _ir(steps=steps)
    from app.analyze.checks.temporal import temporal_checks

    diags = temporal_checks(ir, None)
    assert any(d.code == "TM003" for d in diags)


# ---------------------------------------------------------------------------
# Language checks (LG)
# ---------------------------------------------------------------------------


def test_lg001_vague_quantifier():
    steps = [
        Step(id="s01", action="provide sufficient documentation", modal=ModalVerb.SHALL)
    ]
    ir = _ir(steps=steps)
    from app.analyze.checks.language import language_checks

    diags = language_checks(ir, None)
    assert any(d.code == "LG001" for d in diags)


def test_lg002_should_modal():
    steps = [Step(id="s01", action="log complaint", modal=ModalVerb.SHOULD)]
    ir = _ir(steps=steps)
    from app.analyze.checks.language import language_checks

    diags = language_checks(ir, None)
    assert any(d.code == "LG002" for d in diags)


def test_lg_checks_are_language_tier():
    steps = [Step(id="s01", action="provide sufficient info", modal=ModalVerb.SHOULD)]
    ir = _ir(steps=steps)
    from app.analyze.checks.language import language_checks

    diags = language_checks(ir, None)
    assert all(d.check_tier == CheckTier.LANGUAGE for d in diags)


# ---------------------------------------------------------------------------
# Z3 decision checks (ST004 / ST005)
# ---------------------------------------------------------------------------


def _make_compare(left: str, op: str, val: float) -> CompareCondition:
    return CompareCondition(
        left=left,
        op=op,
        right=TypedValue(value_type=ValueType.NUMBER, number=val),
    )


def test_st004_non_exhaustive_decision():
    dec = Decision(
        id="d01",
        question="Is amount small?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(
                label="small",
                condition=_make_compare("amount", "lt", 100.0),
                next_step_id="s02",
            ),
            DecisionBranch(
                label="large",
                condition=_make_compare("amount", "gt", 200.0),
                next_step_id="s03",
            ),
        ],
    )
    ir = _ir(
        steps=[
            Step(id="s01", action="assess", modal=ModalVerb.SHALL),
            Step(id="s02", action="small path", modal=ModalVerb.SHALL),
            Step(id="s03", action="large path", modal=ModalVerb.SHALL),
        ],
        decisions=[dec],
    )
    from app.analyze.checks.decisions_z3 import decision_checks

    diags = decision_checks(ir, None)
    assert any(d.code == "ST004" for d in diags)


def test_st005_overlapping_branches():
    dec = Decision(
        id="d01",
        question="Is amount big?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(
                label="ge50",
                condition=_make_compare("amount", "ge", 50.0),
                next_step_id="s02",
            ),
            DecisionBranch(
                label="ge100",
                condition=_make_compare("amount", "ge", 100.0),
                next_step_id="s03",
            ),
        ],
    )
    ir = _ir(
        steps=[
            Step(id="s01", action="assess", modal=ModalVerb.SHALL),
            Step(id="s02", action="path a", modal=ModalVerb.SHALL),
            Step(id="s03", action="path b", modal=ModalVerb.SHALL),
        ],
        decisions=[dec],
    )
    from app.analyze.checks.decisions_z3 import decision_checks

    diags = decision_checks(ir, None)
    assert any(d.code == "ST005" for d in diags)


def test_st004_exactly_two_exhaustive_branches_no_error():
    dec = Decision(
        id="d01",
        question="Is amount below threshold?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(
                label="below",
                condition=_make_compare("amount", "lt", 100.0),
                next_step_id="s02",
            ),
            DecisionBranch(
                label="ge",
                condition=_make_compare("amount", "ge", 100.0),
                next_step_id="s03",
            ),
        ],
    )
    ir = _ir(
        steps=[
            Step(id="s01", action="assess", modal=ModalVerb.SHALL),
            Step(id="s02", action="below path", modal=ModalVerb.SHALL),
            Step(id="s03", action="above path", modal=ModalVerb.SHALL),
        ],
        decisions=[dec],
    )
    from app.analyze.checks.decisions_z3 import decision_checks

    diags = decision_checks(ir, None)
    assert not any(d.code == "ST004" for d in diags)


def test_z3_skips_vague_conditions():
    dec = Decision(
        id="d01",
        question="Is it urgent?",
        preceding_step_id="s01",
        branches=[
            DecisionBranch(
                label="urgent", condition=VagueCondition(text="urgent"), next_step_id="s02"
            ),
            DecisionBranch(
                label="normal", condition=VagueCondition(text="normal"), next_step_id="s03"
            ),
        ],
    )
    ir = _ir(
        steps=[
            Step(id="s01", action="assess", modal=ModalVerb.SHALL),
            Step(id="s02", action="urgent path", modal=ModalVerb.SHALL),
            Step(id="s03", action="normal path", modal=ModalVerb.SHALL),
        ],
        decisions=[dec],
    )
    from app.analyze.checks.decisions_z3 import decision_checks

    # Should not raise; Z3 is silently skipped for vague conditions
    diags = decision_checks(ir, None)
    assert isinstance(diags, list)


# ---------------------------------------------------------------------------
# Analyzer service (integration — no DB)
# ---------------------------------------------------------------------------


class _FakeServices:
    """Stub services that satisfies the singleton protocol."""

    _singletons: dict = {}

    def singleton(self, key, factory):
        if key not in self._singletons:
            self._singletons[key] = factory()
        return self._singletons[key]


def test_analyzer_analyze_returns_report():

    analyzer = Analyzer.__new__(Analyzer)
    ir = _ir()
    report = analyzer.analyze(ir, None, "run1")
    assert report.run_id == "run1"
    assert isinstance(report.diagnostics, list)
    assert report.stats["total"] == len(report.diagnostics)
