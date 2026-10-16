"""6.3 Fault-injection test generation.

Generates test cases that stress-test resilience:
- ACTOR_UNAVAILABLE: each actor role set to None (absent)
- SYSTEM_DOWN: each IT system set to False (unavailable)

No LLM calls.
"""

from __future__ import annotations

import re

from app.schemas.ir_sop import SopIR
from app.schemas.testcase import TestCase, TestOrigin
from app.schemas.trace import Scenario


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", text.lower()).strip("_")


def generate_actor_fault_tests(ir: SopIR) -> list[TestCase]:
    """For each actor role in each process, generate a scenario with that role unavailable."""
    tests: list[TestCase] = []
    for proc in ir.processes:
        roles_in_proc: set[str] = set()
        for step in proc.steps:
            if step.actor_role_id:
                roles_in_proc.add(step.actor_role_id)
        for role_id in sorted(roles_in_proc):
            sc_id = f"sc_fault_actor_{_slug(proc.id)}_{_slug(role_id)}"
            tests.append(
                TestCase(
                    id=sc_id,
                    description=(
                        f"Fault: actor '{role_id}' unavailable in process '{proc.name}'"
                    ),
                    origin=TestOrigin.FAULT,
                    process_id=proc.id,
                    scenario=Scenario(
                        id=sc_id,
                        description=f"Actor '{role_id}' unavailable",
                        process_id=proc.id,
                        actor_overrides={role_id: None},
                    ),
                    tags=["fault:actor", f"role:{role_id}"],
                )
            )
    return tests


def generate_system_fault_tests(ir: SopIR) -> list[TestCase]:
    """For each IT system referenced in each process, generate a 'system down' scenario."""
    tests: list[TestCase] = []
    for proc in ir.processes:
        systems_in_proc: set[str] = set()
        for step in proc.steps:
            for sys_id in step.systems:
                systems_in_proc.add(sys_id)
        for sys_id in sorted(systems_in_proc):
            sc_id = f"sc_fault_sys_{_slug(proc.id)}_{_slug(sys_id)}"
            tests.append(
                TestCase(
                    id=sc_id,
                    description=(
                        f"Fault: system '{sys_id}' down in process '{proc.name}'"
                    ),
                    origin=TestOrigin.FAULT,
                    process_id=proc.id,
                    scenario=Scenario(
                        id=sc_id,
                        description=f"System '{sys_id}' down",
                        process_id=proc.id,
                        system_overrides={sys_id: False},
                    ),
                    tags=["fault:system", f"system:{sys_id}"],
                )
            )
    return tests
