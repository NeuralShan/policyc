"""TestGenService: orchestrates the three generators for Layer 6."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.services import Services
from app.models import TestSuiteRecord
from app.schemas.ir_sop import SopIR
from app.schemas.testcase import TestSuite
from app.testgen.deterministic import generate_boundary_tests, generate_path_tests
from app.testgen.faults import generate_actor_fault_tests, generate_system_fault_tests
from app.testgen.solver import generate_branch_tests

log = logging.getLogger(__name__)


def get_testgen(services: Services) -> TestGenService:
    return services.singleton("testgen", lambda: TestGenService(services))


class TestGenService:
    def __init__(self, services: Services) -> None:
        self._services = services

    def generate(self, ir: SopIR, run_id: str) -> TestSuite:
        """Run all generators and return the deduped, annotated suite."""
        all_tests = []
        all_tests.extend(generate_path_tests(ir))
        all_tests.extend(generate_boundary_tests(ir))
        all_tests.extend(generate_branch_tests(ir))
        all_tests.extend(generate_actor_fault_tests(ir))
        all_tests.extend(generate_system_fault_tests(ir))

        # Deduplicate by ID (first occurrence wins)
        seen: set[str] = set()
        unique = []
        for tc in all_tests:
            if tc.id not in seen:
                seen.add(tc.id)
                unique.append(tc)

        suite = TestSuite(run_id=run_id, test_cases=unique).with_stats()
        log.info(
            "testgen: %d test cases  boundary=%d  branch=%d  fault=%d  path=%d",
            suite.stats.get("total", 0),
            suite.stats.get("boundary", 0),
            suite.stats.get("branch", 0),
            suite.stats.get("fault", 0),
            suite.stats.get("path", 0),
        )
        return suite

    def save(self, suite: TestSuite) -> TestSuiteRecord:
        with self._services.sessions() as session:
            record = TestSuiteRecord(
                run_id=suite.run_id,
                suite=suite.model_dump(mode="json"),
                stats=suite.stats,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def load(self, run_id: str) -> TestSuite | None:
        with self._services.sessions() as session:
            stmt = (
                select(TestSuiteRecord)
                .where(TestSuiteRecord.run_id == run_id)
                .order_by(TestSuiteRecord.created_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            return TestSuite.model_validate(record.suite)
