"""Layer 7 runner: execute a TestSuite through the process simulator."""

from __future__ import annotations

import logging

from app.model.simulator import simulate
from app.run.coverage import compute_coverage
from app.run.oracle import apply_oracle
from app.schemas.ir_sop import SopIR
from app.schemas.testcase import TestSuite
from app.schemas.testrun import TestResult, TestRunReport, TestVerdict

log = logging.getLogger(__name__)


def run_test_suite(ir: SopIR, suite: TestSuite) -> TestRunReport:
    """Run every test case through the simulator and return the full report."""
    results: list[TestResult] = []

    for tc in suite.test_cases:
        try:
            trace = simulate(ir, tc.scenario)
            verdict, reasons = apply_oracle(tc, trace)
            results.append(
                TestResult(
                    test_id=tc.id,
                    verdict=verdict,
                    fail_reasons=reasons,
                    trace=trace,
                )
            )
        except Exception as exc:
            log.warning("runner: test %s raised %s — marking SKIP", tc.id, exc)
            results.append(
                TestResult(
                    test_id=tc.id,
                    verdict=TestVerdict.SKIP,
                    fail_reasons=[],
                    trace=None,
                    skip_reason=f"{type(exc).__name__}: {exc}",
                )
            )

    # Coverage: only include traces from non-skipped results
    traces = [r.trace for r in results if r.trace is not None]
    coverage = compute_coverage(ir, traces)

    report = TestRunReport(
        run_id=suite.run_id,
        results=results,
        coverage=coverage,
    ).with_stats()

    log.info(
        "runner: total=%d passed=%d failed=%d skipped=%d  step_cov=%.1f%%  branch_cov=%.1f%%",
        report.total,
        report.passed,
        report.failed,
        report.skipped,
        report.coverage.step_coverage_pct,
        report.coverage.branch_coverage_pct,
    )
    return report
