"""Coverage Report for V-model traceability framework.

DC-006: Produces a structured report with four coverage gap sections:
  1. Requirements with no FULFILLED_BY edges (unimplemented)
  2. Design contracts with no VERIFIED_BY edges (unverified)
  3. Test cases with no ValidationResult nodes referencing them (unexecuted)
  4. Requirements with no end-to-end path to any ValidationResult
     (Requirement->FULFILLED_BY->DesignContract->VERIFIED_BY->TestCase<-ValidationResult)

REQ-013 (Sprint-Scoped Coverage Filter): An optional ``req_ids`` list scopes the
report to a subset of requirements. When provided, sections 1 and 4 are filtered
to those requirement IDs; sections 2 and 3 are scoped to the design contracts
and test cases reachable from those requirements. ``None`` preserves the
existing unfiltered behavior.

Guarantees:
- All four gap categories from REQ-007 are reported
- Each section lists affected node IDs and titles
- Section 4 performs multi-hop traversal
- Summary counts provided for each section
- Output is deterministically ordered within each section
- An empty ``req_ids`` list yields an empty report (zero-scope = zero gaps)
- Unknown requirement IDs in ``req_ids`` are silently ignored — they simply
  match nothing in the graph and contribute no gaps

Error Semantics:
- Fails on missing or corrupt database (FileNotFoundError, RuntimeError)
- Raises RuntimeError if required node tables (Requirement, DesignContract, TestCase) are missing
- Raises RuntimeError if required edge tables (FULFILLED_BY, VERIFIED_BY) are missing —
  a missing edge table means the graph is incomplete, not that all items have gaps.
  Treating a schema error as a coverage gap would produce false negatives, which are
  unacceptable in a medical-grade traceability tool.
- If ValidationResult table is absent, ALL test cases are reported unexecuted
  and ALL requirements are reported as end-to-end gaps (absence is not silence)

Design Note — test_id property linkage (Sections 3 and 4):
  ValidationResult nodes carry a ``test_id`` STRING property whose value matches the
  ``id`` property of a TestCase node.  This is a deliberate property-based linkage:
  it mirrors the way test runners record which test produced a result without requiring
  the graph to contain an explicit VALIDATES edge.  Sections 3 and 4 intentionally use
  this ``test_id`` property (not a graph edge) to determine whether a TestCase has been
  executed.  The guard ``if row[0]:`` at the collection point ensures that a NULL or
  empty ``test_id`` does NOT mark any test case as executed.

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


def _query_unimplemented_requirements(conn: kuzu.Connection, req_ids: list[str] | None = None) -> list[CoverageItem]:
    """Find requirements with no FULFILLED_BY edges.

    Args:
        conn: Active Kuzu connection with Requirement and FULFILLED_BY tables present.
        req_ids: Optional list of requirement IDs to scope the query to.
            ``None`` reports all requirements; an empty list returns no items.

    Returns:
        List of CoverageItems for unimplemented requirements, ordered by ID.
    """
    edge_missing = _verify_schema(conn, ["FULFILLED_BY"])
    if edge_missing:
        # A missing FULFILLED_BY table means the graph schema is incomplete.
        # Treating every requirement as unimplemented would be a false negative — the
        # absence of the edge table tells us nothing about actual implementation status.
        # Fail loudly so the caller knows the graph cannot be trusted.
        raise RuntimeError(f"Missing required edge tables: {edge_missing}")

    if req_ids is not None and not req_ids:
        return []

    scope_clause = "AND r.id IN $req_ids " if req_ids else ""
    params = {"req_ids": req_ids} if req_ids else {}
    result = conn.execute(
        "MATCH (r:Requirement) "
        "WHERE NOT EXISTS { MATCH (r)-[:FULFILLED_BY]->(:DesignContract) } "
        f"{scope_clause}"
        "RETURN r.id, r.title "
        "ORDER BY r.id",
        params,
    )
    items = []
    while result.has_next():
        row = result.get_next()
        items.append(CoverageItem(id=row[0], title=row[1]))
    return items


def _query_unverified_contracts(conn: kuzu.Connection, req_ids: list[str] | None = None) -> list[CoverageItem]:
    """Find design contracts with no VERIFIED_BY edges.

    Args:
        conn: Active Kuzu connection with DesignContract and VERIFIED_BY tables present.
        req_ids: Optional list of requirement IDs to scope the query to. When provided,
            only contracts reachable from those requirements via FULFILLED_BY are reported.
            ``None`` reports all unverified contracts; an empty list returns no items.

    Returns:
        List of CoverageItems for unverified contracts, ordered by ID.
    """
    edge_missing = _verify_schema(conn, ["VERIFIED_BY"])
    if edge_missing:
        # A missing VERIFIED_BY table means the graph schema is incomplete.
        # Treating every contract as unverified would be a false negative — the
        # absence of the edge table tells us nothing about actual verification status.
        # Fail loudly so the caller knows the graph cannot be trusted.
        raise RuntimeError(f"Missing required edge tables: {edge_missing}")

    if req_ids is not None and not req_ids:
        return []

    if req_ids:
        # Scoped: only contracts reachable from the requirements in scope.
        # Requires FULFILLED_BY to be present so we can traverse to in-scope contracts.
        fulfilled_missing = _verify_schema(conn, ["FULFILLED_BY"])
        if fulfilled_missing:
            raise RuntimeError(f"Missing required edge tables: {fulfilled_missing}")
        result = conn.execute(
            "MATCH (r:Requirement)-[:FULFILLED_BY]->(dc:DesignContract) "
            "WHERE r.id IN $req_ids "
            "AND NOT EXISTS { MATCH (dc)-[:VERIFIED_BY]->(:TestCase) } "
            "RETURN DISTINCT dc.id, dc.title, dc.module "
            "ORDER BY dc.id",
            {"req_ids": req_ids},
        )
    else:
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


def _query_unexecuted_tests(conn: kuzu.Connection, vr_missing: bool, req_ids: list[str] | None = None) -> list[CoverageItem]:
    """Find test cases with no ValidationResult referencing them.

    ValidationResult nodes carry a test_id property that links back to a TestCase.
    If the ValidationResult table is absent entirely, ALL test cases are unexecuted —
    this is reported rather than silently returning empty results.

    Args:
        conn: Active Kuzu connection with TestCase table present.
        vr_missing: True if ValidationResult table does not exist in the graph.
        req_ids: Optional list of requirement IDs to scope the query to. When provided,
            only test cases reachable from those requirements via
            FULFILLED_BY → VERIFIED_BY are reported. ``None`` reports all test cases;
            an empty list returns no items.

    Returns:
        List of CoverageItems for unexecuted test cases, ordered by ID.
    """
    if req_ids is not None and not req_ids:
        return []

    if req_ids:
        # Scoped: only test cases reachable from the requirements in scope.
        # Requires FULFILLED_BY and VERIFIED_BY to traverse to in-scope test cases.
        edge_missing = _verify_schema(conn, ["FULFILLED_BY", "VERIFIED_BY"])
        if edge_missing:
            raise RuntimeError(f"Missing required edge tables: {edge_missing}")
        result = conn.execute(
            "MATCH (r:Requirement)-[:FULFILLED_BY]->(:DesignContract)-[:VERIFIED_BY]->(tc:TestCase) "
            "WHERE r.id IN $req_ids "
            "RETURN DISTINCT tc.id, tc.title "
            "ORDER BY tc.id",
            {"req_ids": req_ids},
        )
    else:
        result = conn.execute("MATCH (tc:TestCase) RETURN tc.id, tc.title ORDER BY tc.id")

    all_tests = []
    while result.has_next():
        row = result.get_next()
        all_tests.append(CoverageItem(id=row[0], title=row[1]))

    if vr_missing:
        # No ValidationResult table: every (in-scope) test case is unexecuted
        return all_tests

    # Collect test IDs that have at least one ValidationResult
    vr_result = conn.execute("MATCH (vr:ValidationResult) RETURN vr.test_id")
    executed_test_ids: set[str] = set()
    while vr_result.has_next():
        row = vr_result.get_next()
        if row[0]:
            executed_test_ids.add(row[0])

    return [tc for tc in all_tests if tc.id not in executed_test_ids]


def _query_end_to_end_gaps(conn: kuzu.Connection, vr_missing: bool, req_ids: list[str] | None = None) -> list[CoverageItem]:
    """Find requirements with no complete end-to-end path to any ValidationResult.

    A requirement has end-to-end coverage when there exists a path:
      Requirement -[FULFILLED_BY]-> DesignContract -[VERIFIED_BY]-> TestCase
    where the TestCase has at least one ValidationResult (test_id match).

    If FULFILLED_BY or VERIFIED_BY tables are missing, raises RuntimeError —
    a missing edge table means the graph is incomplete, not that all requirements
    have gaps (which would be a false negative).
    If ValidationResult table is missing (vr_missing=True), ALL requirements have
    end-to-end gaps regardless of graph edges — absence of results is not silence.

    Args:
        conn: Active Kuzu connection with Requirement table present.
        vr_missing: True if ValidationResult table does not exist in the graph.
        req_ids: Optional list of requirement IDs to scope the query to.
            ``None`` reports gaps for all requirements; an empty list returns no items.

    Returns:
        List of CoverageItems for requirements with end-to-end gaps, ordered by ID.
    """
    if req_ids is not None and not req_ids:
        return []

    if req_ids:
        result = conn.execute(
            "MATCH (r:Requirement) WHERE r.id IN $req_ids RETURN r.id, r.title ORDER BY r.id",
            {"req_ids": req_ids},
        )
    else:
        result = conn.execute("MATCH (r:Requirement) RETURN r.id, r.title ORDER BY r.id")
    all_reqs = []
    while result.has_next():
        row = result.get_next()
        all_reqs.append(CoverageItem(id=row[0], title=row[1]))

    if vr_missing:
        # No ValidationResult table: every (in-scope) requirement has an end-to-end gap
        return all_reqs

    # Check for required edge tables — missing means the graph schema is incomplete.
    # Returning all requirements as gaps would be a false negative: we cannot distinguish
    # "no path exists" from "no path was recorded" when the edge table itself is absent.
    edge_missing = _verify_schema(conn, ["FULFILLED_BY", "VERIFIED_BY"])
    if edge_missing:
        raise RuntimeError(f"Missing required edge tables: {edge_missing}")

    # Build set of test IDs that have been executed (have a ValidationResult)
    vr_result = conn.execute("MATCH (vr:ValidationResult) RETURN vr.test_id")
    executed_test_ids: set[str] = set()
    while vr_result.has_next():
        row = vr_result.get_next()
        if row[0]:
            executed_test_ids.add(row[0])

    # For each requirement, check if any path through FULFILLED_BY→VERIFIED_BY
    # leads to a TestCase with a ValidationResult.
    if req_ids:
        path_result = conn.execute(
            "MATCH (r:Requirement)-[:FULFILLED_BY]->(dc:DesignContract)-[:VERIFIED_BY]->(tc:TestCase) "
            "WHERE r.id IN $req_ids "
            "RETURN r.id, tc.id "
            "ORDER BY r.id",
            {"req_ids": req_ids},
        )
    else:
        path_result = conn.execute(
            "MATCH (r:Requirement)-[:FULFILLED_BY]->(dc:DesignContract)-[:VERIFIED_BY]->(tc:TestCase) "
            "RETURN r.id, tc.id "
            "ORDER BY r.id"
        )
    covered_req_ids: set[str] = set()
    while path_result.has_next():
        row = path_result.get_next()
        req_id = row[0]
        tc_id = row[1]
        if tc_id in executed_test_ids:
            covered_req_ids.add(req_id)

    return [r for r in all_reqs if r.id not in covered_req_ids]


def run_coverage_report(db_path: Path, req_ids: list[str] | None = None) -> CoverageReport:
    """Run coverage report on a traceability graph, optionally scoped to a set of requirements.

    Produces a structured report with four gap sections:
    1. Requirements with no FULFILLED_BY edges (unimplemented)
    2. Design contracts with no VERIFIED_BY edges (unverified)
    3. Test cases with no ValidationResult nodes (unexecuted)
    4. Requirements with no end-to-end path to any ValidationResult

    If ValidationResult table is absent from the graph, sections 3 and 4 report
    ALL (in-scope) test cases and requirements as gaps rather than returning empty
    results. False negatives hide problems — this is a design principle for
    traceability tools.

    Sprint scoping (REQ-013):
        When ``req_ids`` is provided, the report is scoped to that subset of
        requirements:
          - Section 1 is filtered to requirements whose ID is in ``req_ids``.
          - Section 2 is filtered to design contracts reachable from those
            requirements via FULFILLED_BY.
          - Section 3 is filtered to test cases reachable from those design
            contracts via VERIFIED_BY.
          - Section 4 is filtered to requirements whose ID is in ``req_ids``.
        An empty ``req_ids`` list yields an empty report (zero-scope = zero
        gaps). Unknown IDs are silently ignored.

    Args:
        db_path: Path to Kuzu database.
        req_ids: Optional list of Requirement IDs that scope the report.
            ``None`` (default) reports gaps across the entire graph.

    Returns:
        CoverageReport with all four gap sections populated.

    Raises:
        FileNotFoundError: If database path doesn't exist.
        RuntimeError: If required node tables (Requirement, DesignContract, TestCase) are missing,
            or if required edge tables (FULFILLED_BY, VERIFIED_BY) are missing.
            A missing table means the graph is incomplete — not that all items have gaps.
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

    report.unimplemented_requirements = _query_unimplemented_requirements(conn, req_ids)
    report.unverified_contracts = _query_unverified_contracts(conn, req_ids)
    report.unexecuted_tests = _query_unexecuted_tests(conn, vr_missing, req_ids)
    report.end_to_end_gaps = _query_end_to_end_gaps(conn, vr_missing, req_ids)

    return report
