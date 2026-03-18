"""Coverage Report for V-model traceability framework.

DC-006: Produces a structured report with four coverage gap sections:
  1. Requirements with no FULFILLED_BY edges (unimplemented)
  2. Design contracts with no VERIFIED_BY edges (unverified)
  3. Test cases with no ValidationResult nodes referencing them (unexecuted)
  4. Requirements with no end-to-end path to any ValidationResult
     (Requirement->FULFILLED_BY->DesignContract->VERIFIED_BY->TestCase<-ValidationResult)

Guarantees:
- All four gap categories from REQ-007 are reported
- Each section lists affected node IDs and titles
- Section 4 performs multi-hop traversal
- Summary counts provided for each section
- Output is deterministically ordered within each section

Error Semantics:
- Fails on missing or corrupt database (FileNotFoundError, RuntimeError)
- Raises RuntimeError if required node tables (Requirement, DesignContract, TestCase) are missing
- If ValidationResult table is absent, ALL test cases are reported unexecuted
  and ALL requirements are reported as end-to-end gaps (absence is not silence)

Usage:
    from scripts.query_coverage import run_coverage_report, CoverageReport
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import kuzu


@dataclass
class CoverageItem:
    """A single node identified as having a coverage gap."""

    id: str
    title: str
    module: str = ""


@dataclass
class CoverageReport:
    """Structured coverage report with four gap sections.

    Attributes:
        unimplemented_requirements: Requirements with no FULFILLED_BY edges.
        unverified_contracts: Design contracts with no VERIFIED_BY edges.
        unexecuted_tests: TestCases with no ValidationResult referencing them.
        end_to_end_gaps: Requirements with no complete path to any ValidationResult.
        validation_result_table_missing: True if the ValidationResult table was absent.
    """

    unimplemented_requirements: list[CoverageItem] = field(default_factory=list)
    unverified_contracts: list[CoverageItem] = field(default_factory=list)
    unexecuted_tests: list[CoverageItem] = field(default_factory=list)
    end_to_end_gaps: list[CoverageItem] = field(default_factory=list)
    validation_result_table_missing: bool = False

    @property
    def summary(self) -> dict[str, int]:
        """Summary counts for each gap category."""
        return {
            "unimplemented_requirements": len(self.unimplemented_requirements),
            "unverified_contracts": len(self.unverified_contracts),
            "unexecuted_tests": len(self.unexecuted_tests),
            "end_to_end_gaps": len(self.end_to_end_gaps),
        }

    @property
    def has_gaps(self) -> bool:
        """True if any coverage gap exists in any section."""
        return bool(
            self.unimplemented_requirements or self.unverified_contracts or self.unexecuted_tests or self.end_to_end_gaps
        )


def _verify_schema(conn: kuzu.Connection, required_tables: list[str]) -> list[str]:
    """Check that expected tables exist in the database.

    Args:
        conn: Kuzu connection.
        required_tables: Table names to check.

    Returns:
        List of missing table names (empty if all present).
    """
    result = conn.execute("CALL show_tables() RETURN name")
    existing = set()
    while result.has_next():
        existing.add(result.get_next()[0])
    return [t for t in required_tables if t not in existing]


def _query_unimplemented_requirements(conn: kuzu.Connection) -> list[CoverageItem]:
    """Find requirements with no FULFILLED_BY edges.

    Args:
        conn: Active Kuzu connection with Requirement and FULFILLED_BY tables present.

    Returns:
        List of CoverageItems for unimplemented requirements, ordered by ID.
    """
    edge_missing = _verify_schema(conn, ["FULFILLED_BY"])
    if edge_missing:
        # No FULFILLED_BY table means ALL requirements are unimplemented
        result = conn.execute("MATCH (r:Requirement) RETURN r.id, r.title ORDER BY r.id")
        items = []
        while result.has_next():
            row = result.get_next()
            items.append(CoverageItem(id=row[0], title=row[1]))
        return items

    result = conn.execute(
        "MATCH (r:Requirement) "
        "WHERE NOT EXISTS { MATCH (r)-[:FULFILLED_BY]->(:DesignContract) } "
        "RETURN r.id, r.title "
        "ORDER BY r.id"
    )
    items = []
    while result.has_next():
        row = result.get_next()
        items.append(CoverageItem(id=row[0], title=row[1]))
    return items


def _query_unverified_contracts(conn: kuzu.Connection) -> list[CoverageItem]:
    """Find design contracts with no VERIFIED_BY edges.

    Args:
        conn: Active Kuzu connection with DesignContract and VERIFIED_BY tables present.

    Returns:
        List of CoverageItems for unverified contracts, ordered by ID.
    """
    edge_missing = _verify_schema(conn, ["VERIFIED_BY"])
    if edge_missing:
        # No VERIFIED_BY table means ALL contracts are unverified
        result = conn.execute("MATCH (dc:DesignContract) RETURN dc.id, dc.title, dc.module ORDER BY dc.id")
        items = []
        while result.has_next():
            row = result.get_next()
            items.append(CoverageItem(id=row[0], title=row[1], module=row[2] or ""))
        return items

    result = conn.execute(
        "MATCH (dc:DesignContract) "
        "WHERE NOT EXISTS { MATCH (dc)-[:VERIFIED_BY]->(:TestCase) } "
        "RETURN dc.id, dc.title, dc.module "
        "ORDER BY dc.id"
    )
    items = []
    while result.has_next():
        row = result.get_next()
        items.append(CoverageItem(id=row[0], title=row[1], module=row[2] or ""))
    return items


def _query_unexecuted_tests(conn: kuzu.Connection, vr_missing: bool) -> list[CoverageItem]:
    """Find test cases with no ValidationResult referencing them.

    ValidationResult nodes carry a test_id property that links back to a TestCase.
    If the ValidationResult table is absent entirely, ALL test cases are unexecuted —
    this is reported rather than silently returning empty results.

    Args:
        conn: Active Kuzu connection with TestCase table present.
        vr_missing: True if ValidationResult table does not exist in the graph.

    Returns:
        List of CoverageItems for unexecuted test cases, ordered by ID.
    """
    result = conn.execute("MATCH (tc:TestCase) RETURN tc.id, tc.title ORDER BY tc.id")
    all_tests = []
    while result.has_next():
        row = result.get_next()
        all_tests.append(CoverageItem(id=row[0], title=row[1]))

    if vr_missing:
        # No ValidationResult table: every test case is unexecuted
        return all_tests

    # Collect test IDs that have at least one ValidationResult
    vr_result = conn.execute("MATCH (vr:ValidationResult) RETURN vr.test_id")
    executed_test_ids: set[str] = set()
    while vr_result.has_next():
        row = vr_result.get_next()
        if row[0]:
            executed_test_ids.add(row[0])

    return [tc for tc in all_tests if tc.id not in executed_test_ids]


def _query_end_to_end_gaps(conn: kuzu.Connection, vr_missing: bool) -> list[CoverageItem]:
    """Find requirements with no complete end-to-end path to any ValidationResult.

    A requirement has end-to-end coverage when there exists a path:
      Requirement -[FULFILLED_BY]-> DesignContract -[VERIFIED_BY]-> TestCase
    where the TestCase has at least one ValidationResult (test_id match).

    If FULFILLED_BY or VERIFIED_BY tables are missing, ALL requirements have
    end-to-end gaps. If ValidationResult table is missing, ALL requirements have
    end-to-end gaps regardless of graph edges.

    Args:
        conn: Active Kuzu connection with Requirement table present.
        vr_missing: True if ValidationResult table does not exist in the graph.

    Returns:
        List of CoverageItems for requirements with end-to-end gaps, ordered by ID.
    """
    result = conn.execute("MATCH (r:Requirement) RETURN r.id, r.title ORDER BY r.id")
    all_reqs = []
    while result.has_next():
        row = result.get_next()
        all_reqs.append(CoverageItem(id=row[0], title=row[1]))

    if vr_missing:
        # No ValidationResult table: every requirement has an end-to-end gap
        return all_reqs

    # Check for required edge tables
    edge_missing = _verify_schema(conn, ["FULFILLED_BY", "VERIFIED_BY"])
    if edge_missing:
        # Cannot traverse: all requirements have end-to-end gaps
        return all_reqs

    # Build set of test IDs that have been executed (have a ValidationResult)
    vr_result = conn.execute("MATCH (vr:ValidationResult) RETURN vr.test_id")
    executed_test_ids: set[str] = set()
    while vr_result.has_next():
        row = vr_result.get_next()
        if row[0]:
            executed_test_ids.add(row[0])

    # For each requirement, check if any path through FULFILLED_BY→VERIFIED_BY
    # leads to a TestCase with a ValidationResult
    covered_req_ids: set[str] = set()
    path_result = conn.execute(
        "MATCH (r:Requirement)-[:FULFILLED_BY]->(dc:DesignContract)-[:VERIFIED_BY]->(tc:TestCase) "
        "RETURN r.id, tc.id "
        "ORDER BY r.id"
    )
    while path_result.has_next():
        row = path_result.get_next()
        req_id = row[0]
        tc_id = row[1]
        if tc_id in executed_test_ids:
            covered_req_ids.add(req_id)

    return [r for r in all_reqs if r.id not in covered_req_ids]


def run_coverage_report(db_path: Path) -> CoverageReport:
    """Run full coverage report on a traceability graph.

    Produces a structured report with four gap sections:
    1. Requirements with no FULFILLED_BY edges (unimplemented)
    2. Design contracts with no VERIFIED_BY edges (unverified)
    3. Test cases with no ValidationResult nodes (unexecuted)
    4. Requirements with no end-to-end path to any ValidationResult

    If ValidationResult table is absent from the graph, sections 3 and 4 report
    ALL test cases and requirements as gaps rather than returning empty results.
    False negatives hide problems — this is a design principle for traceability tools.

    Args:
        db_path: Path to Kuzu database.

    Returns:
        CoverageReport with all four gap sections populated.

    Raises:
        FileNotFoundError: If database path doesn't exist.
        RuntimeError: If required node tables (Requirement, DesignContract, TestCase) are missing.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    # Required node tables — missing any is a fatal error (could mask real gaps)
    missing = _verify_schema(conn, ["Requirement", "DesignContract", "TestCase"])
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")

    report = CoverageReport()

    # Determine if ValidationResult table exists
    vr_missing = bool(_verify_schema(conn, ["ValidationResult"]))
    report.validation_result_table_missing = vr_missing

    report.unimplemented_requirements = _query_unimplemented_requirements(conn)
    report.unverified_contracts = _query_unverified_contracts(conn)
    report.unexecuted_tests = _query_unexecuted_tests(conn, vr_missing)
    report.end_to_end_gaps = _query_end_to_end_gaps(conn, vr_missing)

    return report
