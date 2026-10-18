"""6.2 Solver-based test generation: Z3 witnesses for decision branches.

For each branch in each decision, find a set of facts that satisfies that branch's
condition (and, when possible, only that branch).  Skips branches whose conditions
are vague or unknown.
"""

from __future__ import annotations

import logging
import re

import z3

from app.logic import ConstraintBuilder
from app.schemas.ir_sop import (
    AlwaysCondition,
    SopIR,
)
from app.schemas.testcase import TestCase, TestOrigin
from app.schemas.trace import Scenario

log = logging.getLogger(__name__)



def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", text.lower()).strip("_")


def generate_branch_tests(ir: SopIR) -> list[TestCase]:
    """For each branch in each decision, ask Z3 for a satisfying assignment."""
    tests: list[TestCase] = []

    for proc in ir.processes:
        for dec in proc.decisions:
            for i, branch in enumerate(dec.branches):
                # AlwaysCondition: no variables needed
                if isinstance(branch.condition, AlwaysCondition):
                    sc_id = f"sc_branch_{_slug(dec.id)}_{i}_always"
                    tests.append(
                        TestCase(
                            id=sc_id,
                            description=(
                                f"Branch '{branch.label}' of decision '{dec.question}'"
                                " (always taken)"
                            ),
                            origin=TestOrigin.BRANCH,
                            process_id=proc.id,
                            scenario=Scenario(
                                id=sc_id,
                                description=f"Always-branch: {branch.label}",
                                process_id=proc.id,
                                facts={},
                            ),
                            expected_branch=branch.label,
                            expected_decision_id=dec.id,
                            tags=[f"decision:{dec.id}", f"branch:{_slug(branch.label)}"],
                        )
                    )
                    continue

                builder = ConstraintBuilder()
                for other in dec.branches:
                    builder.scan(other.condition)
                formula = builder.formula(branch.condition)
                if formula is None:
                    log.debug(
                        "solver: skipping branch '%s' of decision '%s' (un-translatable)",
                        branch.label,
                        dec.id,
                    )
                    continue

                solver = z3.Solver()
                solver.add(*builder.domain(), formula)
                if solver.check() != z3.sat:
                    log.debug(
                        "solver: branch '%s' of decision '%s' is unsatisfiable",
                        branch.label,
                        dec.id,
                    )
                    continue

                facts = builder.facts(solver.model())
                sc_id = (
                    f"sc_branch_{_slug(dec.id)}_{i}_{_slug(branch.label)}"
                )
                tests.append(
                    TestCase(
                        id=sc_id,
                        description=(
                            f"Z3 witness for branch '{branch.label}'"
                            f" of decision '{dec.question}'"
                        ),
                        origin=TestOrigin.BRANCH,
                        process_id=proc.id,
                        scenario=Scenario(
                            id=sc_id,
                            description=f"Z3 witness: {branch.label}",
                            process_id=proc.id,
                            facts=facts,
                        ),
                        expected_branch=branch.label,
                        expected_decision_id=dec.id,
                        tags=[f"decision:{dec.id}", f"branch:{_slug(branch.label)}"],
                    )
                )

    return tests
