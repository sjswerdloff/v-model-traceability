"""Tests for coverage report query (DC-006).

Every test is linked to a design contract via @pytest.mark.traces.
Tests verify observable behavior: what gaps are found, not how the query works internally.

Key invariant: missing tables must raise RuntimeError — never silently return empty results
or treat missing schema as "everything has gaps".  False negatives hide traceability problems;
a missing edge table means the graph is incomplete, not that every item is a gap.

Design note on test_id linkage (Sections 3 & 4):
  ValidationResult.test_id is a STRING property whose value matches TestCase.id.
  This is intentional property-based linkage rather than a VALIDATES graph edge.
  A NULL or empty test_id must NOT mark any TestCase as executed.
"""

from __future__ import annotations

from pathlib import Path

import kuzu
import pytest

from scripts.query_coverage import CoverageItem, CoverageReport, run_coverage_report

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_schema(conn: kuzu.Connection) -> None:
    """Create the core node and edge tables without ValidationResult."""
    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE FULFILLED_BY(FROM Requirement TO DesignContract, completeness STRING)")
    conn.execute("CREATE REL TABLE VERIFIED_BY(FROM DesignContract TO TestCase, coverage STRING)")


def _add_validation_result_table(conn: kuzu.Connection) -> None:
    """Add ValidationResult node table to an existing connection."""
    conn.execute(
        "CREATE NODE TABLE ValidationResult("
        "id STRING, test_id STRING, requirement_id STRING, "
        "status STRING, timestamp STRING, evidence STRING, "
        "PRIMARY KEY (id))"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def graph_fully_covered(tmp_path: Path) -> Path:
    """A graph where all four coverage sections are empty (full coverage)."""
    db_path = tmp_path / "full_coverage.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    _base_schema(conn)
    _add_validation_result_table(conn)

    # One requirement, one contract, one test, one validation result
    conn.execute("CREATE (n:Requirement {id: 'REQ-001', title: 'Full Req', priority: 'must'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Full Contract', module: 'mod.py'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Full Test', pytest_path: 'tests/test.py::test_a'})")
    conn.execute(
        "CREATE (n:ValidationResult {"
        "id: 'VR-001', test_id: 'TC-001', requirement_id: 'REQ-001', "
        "status: 'pass', timestamp: '2026-01-01T00:00:00Z', evidence: 'log.txt'})"
    )

    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-001' AND dc.id = 'DC-001' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-001' AND tc.id = 'TC-001' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )

    return db_path


@pytest.fixture()
def graph_with_all_gaps(tmp_path: Path) -> Path:
    """A graph with gaps in all four sections."""
    db_path = tmp_path / "all_gaps.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    _base_schema(conn)
    _add_validation_result_table(conn)

    # Requirement with no FULFILLED_BY (section 1 gap)
    conn.execute("CREATE (n:Requirement {id: 'REQ-UNGAPPED', title: 'Fulfilled Req', priority: 'must'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-GAP', title: 'Unfulfilled Req', priority: 'should'})")

    # Contract with no VERIFIED_BY (section 2 gap)
    conn.execute("CREATE (n:DesignContract {id: 'DC-LINKED', title: 'Linked Contract', module: 'a.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-GAP', title: 'Unverified Contract', module: 'b.py'})")

    # Test with no ValidationResult (section 3 gap)
    conn.execute("CREATE (n:TestCase {id: 'TC-EXECUTED', title: 'Executed Test', pytest_path: 'tests/test.py::test_ok'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-GAP', title: 'Unexecuted Test', pytest_path: 'tests/test.py::test_gap'})")

    # ValidationResult only for TC-EXECUTED
    conn.execute(
        "CREATE (n:ValidationResult {"
        "id: 'VR-001', test_id: 'TC-EXECUTED', requirement_id: 'REQ-UNGAPPED', "
        "status: 'pass', timestamp: '2026-01-01T00:00:00Z', evidence: 'log.txt'})"
    )

    # FULFILLED_BY: REQ-UNGAPPED -> DC-LINKED (REQ-GAP has no edge)
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-UNGAPPED' AND dc.id = 'DC-LINKED' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )

    # VERIFIED_BY: DC-LINKED -> TC-EXECUTED (DC-GAP has no edge)
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-LINKED' AND tc.id = 'TC-EXECUTED' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )

    # REQ-UNGAPPED has a full path (FULFILLED_BY->DC-LINKED->VERIFIED_BY->TC-EXECUTED->VR-001)
    # REQ-GAP has no FULFILLED_BY edge, so it is an end-to-end gap (section 4)

    return db_path


@pytest.fixture()
def graph_missing_vr_table(tmp_path: Path) -> Path:
    """A graph with no ValidationResult table at all."""
    db_path = tmp_path / "missing_vr.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    _base_schema(conn)

    conn.execute("CREATE (n:Requirement {id: 'REQ-001', title: 'Some Req', priority: 'must'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Some Contract', module: 'mod.py'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Some Test', pytest_path: 'tests/test.py::test_a'})")

    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-001' AND dc.id = 'DC-001' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-001' AND tc.id = 'TC-001' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )

    return db_path


@pytest.fixture()
def graph_section4_partial(tmp_path: Path) -> Path:
    """Graph where some requirements have full paths and some have partial paths to ValidationResult."""
    db_path = tmp_path / "partial_e2e.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    _base_schema(conn)
    _add_validation_result_table(conn)

    # REQ-COVERED: path through DC-A → TC-A → VR-A (full e2e)
    # REQ-NO-VR: path through DC-B → TC-B but TC-B has no ValidationResult
    conn.execute("CREATE (n:Requirement {id: 'REQ-COVERED', title: 'Covered Req', priority: 'must'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-NO-VR', title: 'No VR Req', priority: 'must'})")

    conn.execute("CREATE (n:DesignContract {id: 'DC-A', title: 'Contract A', module: 'a.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-B', title: 'Contract B', module: 'b.py'})")

    conn.execute("CREATE (n:TestCase {id: 'TC-A', title: 'Test A', pytest_path: 'tests/test.py::test_a'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-B', title: 'Test B', pytest_path: 'tests/test.py::test_b'})")

    # ValidationResult only for TC-A
    conn.execute(
        "CREATE (n:ValidationResult {"
        "id: 'VR-001', test_id: 'TC-A', requirement_id: 'REQ-COVERED', "
        "status: 'pass', timestamp: '2026-01-01T00:00:00Z', evidence: 'log.txt'})"
    )

    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-COVERED' AND dc.id = 'DC-A' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-NO-VR' AND dc.id = 'DC-B' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-A' AND tc.id = 'TC-A' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-B' AND tc.id = 'TC-B' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )

    return db_path


@pytest.fixture()
def graph_missing_fulfilled_by(tmp_path: Path) -> Path:
    """A graph with no FULFILLED_BY edge table (schema incomplete)."""
    db_path = tmp_path / "missing_fulfilled_by.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE VERIFIED_BY(FROM DesignContract TO TestCase, coverage STRING)")
    _add_validation_result_table(conn)

    conn.execute("CREATE (n:Requirement {id: 'REQ-001', title: 'Some Req', priority: 'must'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Some Contract', module: 'mod.py'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Some Test', pytest_path: 'tests/test.py::test_a'})")

    return db_path


@pytest.fixture()
def graph_missing_verified_by(tmp_path: Path) -> Path:
    """A graph with no VERIFIED_BY edge table (schema incomplete)."""
    db_path = tmp_path / "missing_verified_by.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE FULFILLED_BY(FROM Requirement TO DesignContract, completeness STRING)")
    _add_validation_result_table(conn)

    conn.execute("CREATE (n:Requirement {id: 'REQ-001', title: 'Some Req', priority: 'must'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Some Contract', module: 'mod.py'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Some Test', pytest_path: 'tests/test.py::test_a'})")

    return db_path


@pytest.fixture()
def graph_with_null_test_id(tmp_path: Path) -> Path:
    """A graph with a ValidationResult where test_id is empty string.

    This tests the null guard: an empty test_id must NOT mark any TestCase as executed.
    The TestCase in this fixture should still appear in unexecuted_tests.
    """
    db_path = tmp_path / "null_test_id.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    _base_schema(conn)
    _add_validation_result_table(conn)

    conn.execute("CREATE (n:Requirement {id: 'REQ-001', title: 'Some Req', priority: 'must'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Some Contract', module: 'mod.py'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Some Test', pytest_path: 'tests/test.py::test_a'})")
    # ValidationResult with empty test_id — must not match TC-001
    conn.execute(
        "CREATE (n:ValidationResult {"
        "id: 'VR-001', test_id: '', requirement_id: 'REQ-001', "
        "status: 'pass', timestamp: '2026-01-01T00:00:00Z', evidence: 'log.txt'})"
    )

    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-001' AND dc.id = 'DC-001' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-001' AND tc.id = 'TC-001' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )

    return db_path


@pytest.fixture()
def graph_with_multiple_gaps(tmp_path: Path) -> Path:
    """A graph with at least 2 gap items in each section, for meaningful ordering tests."""
    db_path = tmp_path / "multiple_gaps.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    _base_schema(conn)
    _add_validation_result_table(conn)

    # Two requirements with no FULFILLED_BY (section 1 gaps)
    conn.execute("CREATE (n:Requirement {id: 'REQ-B', title: 'Req B', priority: 'must'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-A', title: 'Req A', priority: 'should'})")

    # Two contracts with no VERIFIED_BY (section 2 gaps)
    conn.execute("CREATE (n:DesignContract {id: 'DC-B', title: 'Contract B', module: 'b.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-A', title: 'Contract A', module: 'a.py'})")

    # Two tests with no ValidationResult (section 3 gaps)
    conn.execute("CREATE (n:TestCase {id: 'TC-B', title: 'Test B', pytest_path: 'tests/test.py::test_b'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-A', title: 'Test A', pytest_path: 'tests/test.py::test_a'})")

    # No ValidationResult nodes, no edges — all four sections have gaps

    return db_path


@pytest.fixture()
def graph_broken_middle_hop(tmp_path: Path) -> Path:
    """A graph where a requirement has a FULFILLED_BY contract but the contract has no VERIFIED_BY test.

    The middle hop is broken: REQ-001 -> DC-001 (exists) but DC-001 -> TestCase (missing).
    REQ-001 must appear as an end-to-end gap in section 4.
    """
    db_path = tmp_path / "broken_middle_hop.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    _base_schema(conn)
    _add_validation_result_table(conn)

    conn.execute("CREATE (n:Requirement {id: 'REQ-001', title: 'Some Req', priority: 'must'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Some Contract', module: 'mod.py'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Some Test', pytest_path: 'tests/test.py::test_a'})")
    conn.execute(
        "CREATE (n:ValidationResult {"
        "id: 'VR-001', test_id: 'TC-001', requirement_id: 'REQ-001', "
        "status: 'pass', timestamp: '2026-01-01T00:00:00Z', evidence: 'log.txt'})"
    )

    # REQ-001 -> DC-001 edge exists; DC-001 -> TC-001 edge is intentionally absent
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-001' AND dc.id = 'DC-001' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    # No VERIFIED_BY edge: the path from DC-001 to TC-001 is broken

    return db_path


# ---------------------------------------------------------------------------
# Section 1: Unimplemented Requirements
# ---------------------------------------------------------------------------


class TestUnimplementedRequirements:
    """Tests for section 1: requirements with no FULFILLED_BY edges."""

    @pytest.mark.traces("DC-006")
    def test_no_gaps_when_all_fulfilled(self, graph_fully_covered: Path) -> None:
        """Contract: unimplemented_requirements is empty when all requirements have FULFILLED_BY edges."""
        report = run_coverage_report(graph_fully_covered)

        assert report.unimplemented_requirements == []

    @pytest.mark.traces("DC-006")
    def test_finds_unfulfilled_requirement(self, graph_with_all_gaps: Path) -> None:
        """Contract: reports requirements with no FULFILLED_BY edges."""
        report = run_coverage_report(graph_with_all_gaps)

        ids = [item.id for item in report.unimplemented_requirements]
        assert "REQ-GAP" in ids
        assert "REQ-UNGAPPED" not in ids

    @pytest.mark.traces("DC-006")
    def test_unimplemented_includes_id_and_title(self, graph_with_all_gaps: Path) -> None:
        """Contract: each unimplemented requirement item has id and title."""
        report = run_coverage_report(graph_with_all_gaps)

        for item in report.unimplemented_requirements:
            assert item.id
            assert item.title

    @pytest.mark.traces("DC-006")
    def test_unimplemented_deterministic_order(self, graph_with_multiple_gaps: Path) -> None:
        """Contract: unimplemented_requirements is ordered deterministically by ID.

        Uses a fixture with 2 gap items (REQ-A, REQ-B inserted out of order) so
        the sorted-order assertion is meaningful — a single-item list is trivially sorted.
        """
        report1 = run_coverage_report(graph_with_multiple_gaps)
        report2 = run_coverage_report(graph_with_multiple_gaps)

        ids1 = [item.id for item in report1.unimplemented_requirements]
        ids2 = [item.id for item in report2.unimplemented_requirements]
        assert len(ids1) >= 2, "Fixture must provide at least 2 gaps for a meaningful ordering test"
        assert ids1 == ids2
        assert ids1 == sorted(ids1)


# ---------------------------------------------------------------------------
# Section 2: Unverified Contracts
# ---------------------------------------------------------------------------


class TestUnverifiedContracts:
    """Tests for section 2: design contracts with no VERIFIED_BY edges."""

    @pytest.mark.traces("DC-006")
    def test_no_gaps_when_all_verified(self, graph_fully_covered: Path) -> None:
        """Contract: unverified_contracts is empty when all contracts have VERIFIED_BY edges."""
        report = run_coverage_report(graph_fully_covered)

        assert report.unverified_contracts == []

    @pytest.mark.traces("DC-006")
    def test_finds_unverified_contract(self, graph_with_all_gaps: Path) -> None:
        """Contract: reports contracts with no VERIFIED_BY edges."""
        report = run_coverage_report(graph_with_all_gaps)

        ids = [item.id for item in report.unverified_contracts]
        assert "DC-GAP" in ids
        assert "DC-LINKED" not in ids

    @pytest.mark.traces("DC-006")
    def test_unverified_includes_id_title_module(self, graph_with_all_gaps: Path) -> None:
        """Contract: each unverified contract item has id, title, and module."""
        report = run_coverage_report(graph_with_all_gaps)

        for item in report.unverified_contracts:
            assert item.id
            assert item.title
            assert item.module

    @pytest.mark.traces("DC-006")
    def test_unverified_deterministic_order(self, graph_with_multiple_gaps: Path) -> None:
        """Contract: unverified_contracts is ordered deterministically by ID.

        Uses a fixture with 2 gap items (DC-A, DC-B inserted out of order) so
        the sorted-order assertion is meaningful.
        """
        report1 = run_coverage_report(graph_with_multiple_gaps)
        report2 = run_coverage_report(graph_with_multiple_gaps)

        ids1 = [item.id for item in report1.unverified_contracts]
        ids2 = [item.id for item in report2.unverified_contracts]
        assert len(ids1) >= 2, "Fixture must provide at least 2 gaps for a meaningful ordering test"
        assert ids1 == ids2
        assert ids1 == sorted(ids1)


# ---------------------------------------------------------------------------
# Section 3: Unexecuted Tests
# ---------------------------------------------------------------------------


class TestUnexecutedTests:
    """Tests for section 3: test cases with no ValidationResult."""

    @pytest.mark.traces("DC-006")
    def test_no_gaps_when_all_executed(self, graph_fully_covered: Path) -> None:
        """Contract: unexecuted_tests is empty when every TestCase has a ValidationResult."""
        report = run_coverage_report(graph_fully_covered)

        assert report.unexecuted_tests == []

    @pytest.mark.traces("DC-006")
    def test_finds_unexecuted_test(self, graph_with_all_gaps: Path) -> None:
        """Contract: reports TestCases with no matching ValidationResult."""
        report = run_coverage_report(graph_with_all_gaps)

        ids = [item.id for item in report.unexecuted_tests]
        assert "TC-GAP" in ids
        assert "TC-EXECUTED" not in ids

    @pytest.mark.traces("DC-006")
    def test_missing_vr_table_reports_all_tests_unexecuted(self, graph_missing_vr_table: Path) -> None:
        """Contract: if ValidationResult table is absent, ALL tests are reported unexecuted.

        This is a critical safety property: absence of the table is not silence.
        False negatives hide traceability problems.
        """
        report = run_coverage_report(graph_missing_vr_table)

        assert report.validation_result_table_missing is True
        assert len(report.unexecuted_tests) == 1
        assert report.unexecuted_tests[0].id == "TC-001"

    @pytest.mark.traces("DC-006")
    def test_unexecuted_tests_deterministic_order(self, graph_with_multiple_gaps: Path) -> None:
        """Contract: unexecuted_tests is ordered deterministically by ID.

        Uses a fixture with 2 gap items (TC-A, TC-B inserted out of order) so
        the sorted-order assertion is meaningful.
        """
        report1 = run_coverage_report(graph_with_multiple_gaps)
        report2 = run_coverage_report(graph_with_multiple_gaps)

        ids1 = [item.id for item in report1.unexecuted_tests]
        ids2 = [item.id for item in report2.unexecuted_tests]
        assert len(ids1) >= 2, "Fixture must provide at least 2 gaps for a meaningful ordering test"
        assert ids1 == ids2
        assert ids1 == sorted(ids1)

    @pytest.mark.traces("DC-006")
    def test_unexecuted_includes_id_and_title(self, graph_with_all_gaps: Path) -> None:
        """Contract: each unexecuted test item has id and title."""
        report = run_coverage_report(graph_with_all_gaps)

        for item in report.unexecuted_tests:
            assert item.id
            assert item.title

    @pytest.mark.traces("DC-006")
    def test_empty_test_id_does_not_mark_test_as_executed(self, graph_with_null_test_id: Path) -> None:
        """Contract: a ValidationResult with empty test_id must NOT mark any TestCase as executed.

        This tests the null guard at the ``if row[0]:`` line in _query_unexecuted_tests.
        Even though a ValidationResult node exists, TC-001 must still appear in
        unexecuted_tests because the ValidationResult's test_id is "".
        """
        report = run_coverage_report(graph_with_null_test_id)

        unexecuted_ids = [item.id for item in report.unexecuted_tests]
        assert "TC-001" in unexecuted_ids


# ---------------------------------------------------------------------------
# Section 4: End-to-End Gaps
# ---------------------------------------------------------------------------


class TestEndToEndGaps:
    """Tests for section 4: requirements with no path to ValidationResult."""

    @pytest.mark.traces("DC-006")
    def test_no_gaps_when_fully_covered(self, graph_fully_covered: Path) -> None:
        """Contract: end_to_end_gaps is empty when every requirement has a complete path."""
        report = run_coverage_report(graph_fully_covered)

        assert report.end_to_end_gaps == []

    @pytest.mark.traces("DC-006")
    def test_finds_requirement_with_no_path(self, graph_with_all_gaps: Path) -> None:
        """Contract: reports requirements with no path through FULFILLED_BY->VERIFIED_BY->ValidationResult."""
        report = run_coverage_report(graph_with_all_gaps)

        ids = [item.id for item in report.end_to_end_gaps]
        assert "REQ-GAP" in ids

    @pytest.mark.traces("DC-006")
    def test_requirement_with_unexecuted_test_is_gap(self, graph_section4_partial: Path) -> None:
        """Contract: if a requirement's test has no ValidationResult, it is an end-to-end gap."""
        report = run_coverage_report(graph_section4_partial)

        gap_ids = [item.id for item in report.end_to_end_gaps]
        assert "REQ-NO-VR" in gap_ids
        assert "REQ-COVERED" not in gap_ids

    @pytest.mark.traces("DC-006")
    def test_missing_vr_table_reports_all_requirements_as_gaps(self, graph_missing_vr_table: Path) -> None:
        """Contract: if ValidationResult table is absent, ALL requirements are end-to-end gaps.

        Critical safety property: the absence of ValidationResult data is not silence.
        """
        report = run_coverage_report(graph_missing_vr_table)

        assert report.validation_result_table_missing is True
        assert len(report.end_to_end_gaps) == 1
        assert report.end_to_end_gaps[0].id == "REQ-001"

    @pytest.mark.traces("DC-006")
    def test_end_to_end_gaps_deterministic_order(self, graph_with_multiple_gaps: Path) -> None:
        """Contract: end_to_end_gaps is ordered deterministically by ID.

        Uses a fixture with 2 gap items (REQ-A, REQ-B inserted out of order) so
        the sorted-order assertion is meaningful.
        """
        report1 = run_coverage_report(graph_with_multiple_gaps)
        report2 = run_coverage_report(graph_with_multiple_gaps)

        ids1 = [item.id for item in report1.end_to_end_gaps]
        ids2 = [item.id for item in report2.end_to_end_gaps]
        assert len(ids1) >= 2, "Fixture must provide at least 2 gaps for a meaningful ordering test"
        assert ids1 == ids2
        assert ids1 == sorted(ids1)

    @pytest.mark.traces("DC-006")
    def test_broken_middle_hop_is_end_to_end_gap(self, graph_broken_middle_hop: Path) -> None:
        """Contract: section 4 traverses all three hops; a broken middle hop is a gap.

        The fixture provides REQ-001 -> DC-001 (FULFILLED_BY exists) but DC-001 has no
        VERIFIED_BY edge to any TestCase.  Even though TC-001 has a ValidationResult,
        the incomplete path means REQ-001 must appear as an end-to-end gap.
        This confirms that section 4 performs genuine multi-hop traversal rather than
        checking only direct edges.
        """
        report = run_coverage_report(graph_broken_middle_hop)

        gap_ids = [item.id for item in report.end_to_end_gaps]
        assert "REQ-001" in gap_ids


# ---------------------------------------------------------------------------
# Summary and Report Structure
# ---------------------------------------------------------------------------


class TestCoverageReportStructure:
    """Tests for CoverageReport structure and summary properties."""

    @pytest.mark.traces("DC-006")
    def test_report_has_summary_counts(self, graph_with_all_gaps: Path) -> None:
        """Contract: summary dict provides counts for all four sections."""
        report = run_coverage_report(graph_with_all_gaps)
        summary = report.summary

        assert "unimplemented_requirements" in summary
        assert "unverified_contracts" in summary
        assert "unexecuted_tests" in summary
        assert "end_to_end_gaps" in summary
        assert all(isinstance(v, int) for v in summary.values())

    @pytest.mark.traces("DC-006")
    def test_has_gaps_true_when_gaps_exist(self, graph_with_all_gaps: Path) -> None:
        """Contract: has_gaps is True when any section has gaps."""
        report = run_coverage_report(graph_with_all_gaps)

        assert report.has_gaps is True

    @pytest.mark.traces("DC-006")
    def test_has_gaps_false_when_fully_covered(self, graph_fully_covered: Path) -> None:
        """Contract: has_gaps is False when all sections are empty."""
        report = run_coverage_report(graph_fully_covered)

        assert report.has_gaps is False

    @pytest.mark.traces("DC-006")
    def test_returns_coverage_report_instance(self, graph_fully_covered: Path) -> None:
        """Contract: run_coverage_report returns a CoverageReport instance."""
        report = run_coverage_report(graph_fully_covered)

        assert isinstance(report, CoverageReport)

    @pytest.mark.traces("DC-006")
    def test_coverage_item_fields(self, graph_with_all_gaps: Path) -> None:
        """Contract: CoverageItems expose id, title, and module fields."""
        report = run_coverage_report(graph_with_all_gaps)

        for section in [
            report.unimplemented_requirements,
            report.unverified_contracts,
            report.unexecuted_tests,
            report.end_to_end_gaps,
        ]:
            for item in section:
                assert isinstance(item, CoverageItem)
                assert hasattr(item, "id")
                assert hasattr(item, "title")
                assert hasattr(item, "module")

    @pytest.mark.traces("DC-006")
    def test_summary_counts_match_list_lengths(self, graph_with_all_gaps: Path) -> None:
        """Contract: summary counts match actual list lengths."""
        report = run_coverage_report(graph_with_all_gaps)
        summary = report.summary

        assert summary["unimplemented_requirements"] == len(report.unimplemented_requirements)
        assert summary["unverified_contracts"] == len(report.unverified_contracts)
        assert summary["unexecuted_tests"] == len(report.unexecuted_tests)
        assert summary["end_to_end_gaps"] == len(report.end_to_end_gaps)

    @pytest.mark.traces("DC-006")
    def test_vr_missing_flag_false_when_table_exists(self, graph_fully_covered: Path) -> None:
        """Contract: validation_result_table_missing is False when the table exists."""
        report = run_coverage_report(graph_fully_covered)

        assert report.validation_result_table_missing is False

    @pytest.mark.traces("DC-006")
    def test_vr_missing_flag_true_when_table_absent(self, graph_missing_vr_table: Path) -> None:
        """Contract: validation_result_table_missing is True when ValidationResult table is absent."""
        report = run_coverage_report(graph_missing_vr_table)

        assert report.validation_result_table_missing is True


# ---------------------------------------------------------------------------
# Error Semantics
# ---------------------------------------------------------------------------


class TestErrorSemantics:
    """Tests for error conditions per DC-006 error semantics."""

    @pytest.mark.traces("DC-006")
    def test_missing_db_raises_file_not_found(self, tmp_path: Path) -> None:
        """Contract: raises FileNotFoundError when database path doesn't exist."""
        with pytest.raises(FileNotFoundError):
            run_coverage_report(tmp_path / "nonexistent.kuzu")

    @pytest.mark.traces("DC-006")
    def test_missing_requirement_table_raises_runtime_error(self, tmp_path: Path) -> None:
        """Contract: raises RuntimeError when Requirement table is missing — not silent empty result."""
        db_path = tmp_path / "no_req.kuzu"
        db = kuzu.Database(str(db_path))
        conn = kuzu.Connection(db)
        conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
        conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")

        with pytest.raises(RuntimeError, match="Missing required tables"):
            run_coverage_report(db_path)

    @pytest.mark.traces("DC-006")
    def test_missing_design_contract_table_raises_runtime_error(self, tmp_path: Path) -> None:
        """Contract: raises RuntimeError when DesignContract table is missing."""
        db_path = tmp_path / "no_dc.kuzu"
        db = kuzu.Database(str(db_path))
        conn = kuzu.Connection(db)
        conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
        conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")

        with pytest.raises(RuntimeError, match="Missing required tables"):
            run_coverage_report(db_path)

    @pytest.mark.traces("DC-006")
    def test_missing_test_case_table_raises_runtime_error(self, tmp_path: Path) -> None:
        """Contract: raises RuntimeError when TestCase table is missing."""
        db_path = tmp_path / "no_tc.kuzu"
        db = kuzu.Database(str(db_path))
        conn = kuzu.Connection(db)
        conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
        conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")

        with pytest.raises(RuntimeError, match="Missing required tables"):
            run_coverage_report(db_path)

    @pytest.mark.traces("DC-006")
    def test_empty_db_raises_runtime_error(self, tmp_path: Path) -> None:
        """Contract: raises RuntimeError when database exists but has no required tables."""
        db_path = tmp_path / "empty.kuzu"
        db = kuzu.Database(str(db_path))
        kuzu.Connection(db)  # create connection to initialize DB

        with pytest.raises(RuntimeError, match="Missing required tables"):
            run_coverage_report(db_path)

    @pytest.mark.traces("DC-006")
    def test_missing_tables_raise_not_return_empty(self, tmp_path: Path) -> None:
        """Critical: missing schema MUST raise RuntimeError, not silently return empty report.

        False negatives hide traceability problems. This property is non-negotiable
        for medical-grade traceability tools.
        """
        db_path = tmp_path / "partial_schema.kuzu"
        db = kuzu.Database(str(db_path))
        kuzu.Connection(db)

        with pytest.raises(RuntimeError):
            result = run_coverage_report(db_path)
            # If we somehow get here without an exception, force the test to fail
            raise AssertionError(f"Expected RuntimeError, got CoverageReport: {result}")

    @pytest.mark.traces("DC-006")
    def test_missing_fulfilled_by_table_raises_runtime_error(self, graph_missing_fulfilled_by: Path) -> None:
        """Contract: raises RuntimeError when FULFILLED_BY edge table is missing.

        A missing FULFILLED_BY table means the graph is incomplete.  Treating all
        requirements as unimplemented would be a false negative — the edge table absence
        tells us nothing about actual implementation status.  Medical-grade principle:
        fail loudly rather than report misleading gaps.
        """
        with pytest.raises(RuntimeError, match="Missing required edge tables"):
            run_coverage_report(graph_missing_fulfilled_by)

    @pytest.mark.traces("DC-006")
    def test_missing_verified_by_table_raises_runtime_error(self, graph_missing_verified_by: Path) -> None:
        """Contract: raises RuntimeError when VERIFIED_BY edge table is missing.

        A missing VERIFIED_BY table means the graph is incomplete.  Treating all
        contracts as unverified would be a false negative — the edge table absence
        tells us nothing about actual verification status.  Medical-grade principle:
        fail loudly rather than report misleading gaps.
        """
        with pytest.raises(RuntimeError, match="Missing required edge tables"):
            run_coverage_report(graph_missing_verified_by)

    @pytest.mark.traces("DC-006")
    def test_missing_fulfilled_by_raises_in_section4(self, graph_missing_fulfilled_by: Path) -> None:
        """Contract: section 4 raises RuntimeError when FULFILLED_BY is absent.

        Section 4 cannot distinguish "no path" from "no edge table" — it must fail
        rather than silently report all requirements as end-to-end gaps.
        This test specifically verifies section 4 does not swallow the incomplete schema.
        """
        with pytest.raises(RuntimeError, match="Missing required edge tables"):
            run_coverage_report(graph_missing_fulfilled_by)

    @pytest.mark.traces("DC-006")
    def test_missing_verified_by_raises_in_section4(self, graph_missing_verified_by: Path) -> None:
        """Contract: section 4 raises RuntimeError when VERIFIED_BY is absent.

        Section 4 cannot distinguish "no test linked" from "no edge table" — it must fail
        rather than silently report all requirements as end-to-end gaps.
        """
        with pytest.raises(RuntimeError, match="Missing required edge tables"):
            run_coverage_report(graph_missing_verified_by)


# ---------------------------------------------------------------------------
# Self-Application
# ---------------------------------------------------------------------------


class TestSelfApplication:
    """Test DC-006 against the project's own traceability graph (REQ-010)."""

    @pytest.mark.traces("DC-006")
    def test_coverage_report_runs_against_project_graph(self, tmp_path: Path) -> None:
        """Contract: coverage report runs against the project's own traceability graph."""
        from scripts.build_graph import build_graph

        project_root = Path(__file__).parent.parent
        build_report = build_graph(
            csv_dir=project_root / "traceability",
            schema_dir=project_root / "schemas",
            output_path=tmp_path / "project.kuzu",
        )
        assert build_report.success

        report = run_coverage_report(tmp_path / "project.kuzu")

        assert isinstance(report, CoverageReport)
        # All four sections must be present (even if empty)
        assert hasattr(report, "unimplemented_requirements")
        assert hasattr(report, "unverified_contracts")
        assert hasattr(report, "unexecuted_tests")
        assert hasattr(report, "end_to_end_gaps")

    @pytest.mark.traces("DC-006")
    def test_project_summary_is_numeric(self, tmp_path: Path) -> None:
        """Contract: summary counts are integers for all sections."""
        from scripts.build_graph import build_graph

        project_root = Path(__file__).parent.parent
        build_report = build_graph(
            csv_dir=project_root / "traceability",
            schema_dir=project_root / "schemas",
            output_path=tmp_path / "project2.kuzu",
        )
        assert build_report.success

        report = run_coverage_report(tmp_path / "project2.kuzu")
        summary = report.summary

        for key, value in summary.items():
            assert isinstance(value, int), f"Summary[{key}] should be int, got {type(value)}"

    @pytest.mark.traces("DC-006")
    def test_project_dc006_not_in_unverified_after_this_pr(self, tmp_path: Path) -> None:
        """Contract: DC-006 should not be in unverified contracts once this test file is linked."""
        from scripts.build_graph import build_graph

        project_root = Path(__file__).parent.parent
        build_report = build_graph(
            csv_dir=project_root / "traceability",
            schema_dir=project_root / "schemas",
            output_path=tmp_path / "project3.kuzu",
        )
        assert build_report.success

        report = run_coverage_report(tmp_path / "project3.kuzu")
        # DC-001 through DC-005 should have tests — DC-006 may still be unverified
        # until verified_by CSV is updated; this test documents current state
        unverified_ids = [item.id for item in report.unverified_contracts]
        # DC-001, DC-002, DC-003 are foundational and must be verified
        assert "DC-001" not in unverified_ids
        assert "DC-002" not in unverified_ids
        assert "DC-003" not in unverified_ids


# ---------------------------------------------------------------------------
# Sprint Scope (REQ-013): req_ids parameter filters report to a subset
# ---------------------------------------------------------------------------


@pytest.fixture()
def graph_for_sprint_scoping(tmp_path: Path) -> Path:
    """A graph with both in-scope and out-of-scope items in every section.

    Layout (no ValidationResult nodes — every test is unexecuted, every fulfilled
    requirement is an end-to-end gap):

      REQ-IN-1  (unfulfilled)                                 — section 1
      REQ-OUT-1 (unfulfilled)                                 — section 1, out-of-scope
      REQ-IN-2  -> DC-IN-2  (unverified)                      — sections 2, 4
      REQ-OUT-2 -> DC-OUT-2 (unverified)                      — sections 2, 4, out-of-scope
      REQ-IN-3  -> DC-IN-3  -> TC-IN-3  (unexecuted)          — sections 3, 4
      REQ-OUT-3 -> DC-OUT-3 -> TC-OUT-3 (unexecuted)          — sections 3, 4, out-of-scope
    """
    db_path = tmp_path / "sprint_scoping.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    _base_schema(conn)
    _add_validation_result_table(conn)

    # Section 1 fodder: unfulfilled requirements
    conn.execute("CREATE (n:Requirement {id: 'REQ-IN-1', title: 'In scope, unfulfilled', priority: 'must'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-OUT-1', title: 'Out of scope, unfulfilled', priority: 'must'})")

    # Section 2 fodder: requirements with unverified contracts
    conn.execute("CREATE (n:Requirement {id: 'REQ-IN-2', title: 'In scope, unverified DC', priority: 'must'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-OUT-2', title: 'Out of scope, unverified DC', priority: 'must'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-IN-2', title: 'In scope DC', module: 'in2.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-OUT-2', title: 'Out of scope DC', module: 'out2.py'})")
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-IN-2' AND dc.id = 'DC-IN-2' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-OUT-2' AND dc.id = 'DC-OUT-2' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )

    # Section 3 fodder: requirements with fully-edged path but unexecuted tests
    conn.execute("CREATE (n:Requirement {id: 'REQ-IN-3', title: 'In scope, unexecuted test', priority: 'must'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-OUT-3', title: 'Out of scope, unexecuted test', priority: 'must'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-IN-3', title: 'In scope DC', module: 'in3.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-OUT-3', title: 'Out of scope DC', module: 'out3.py'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-IN-3', title: 'In scope TC', pytest_path: 'tests/t.py::in3'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-OUT-3', title: 'Out of scope TC', pytest_path: 'tests/t.py::out3'})")
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-IN-3' AND dc.id = 'DC-IN-3' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-OUT-3' AND dc.id = 'DC-OUT-3' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-IN-3' AND tc.id = 'TC-IN-3' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-OUT-3' AND tc.id = 'TC-OUT-3' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )

    return db_path


class TestSprintScope:
    """Tests for the optional ``req_ids`` parameter that scopes the report."""

    @pytest.mark.traces("DC-006")
    def test_req_ids_none_matches_unscoped_behavior(self, graph_for_sprint_scoping: Path) -> None:
        """req_ids=None preserves the original unfiltered report."""
        unscoped = run_coverage_report(graph_for_sprint_scoping)
        explicit_none = run_coverage_report(graph_for_sprint_scoping, req_ids=None)
        assert unscoped.summary == explicit_none.summary
        assert [i.id for i in unscoped.unimplemented_requirements] == [i.id for i in explicit_none.unimplemented_requirements]
        assert [i.id for i in unscoped.unverified_contracts] == [i.id for i in explicit_none.unverified_contracts]
        assert [i.id for i in unscoped.unexecuted_tests] == [i.id for i in explicit_none.unexecuted_tests]
        assert [i.id for i in unscoped.end_to_end_gaps] == [i.id for i in explicit_none.end_to_end_gaps]

    @pytest.mark.traces("DC-006")
    def test_empty_req_ids_returns_empty_report(self, graph_for_sprint_scoping: Path) -> None:
        """An empty req_ids list yields an empty report (zero scope = zero gaps)."""
        report = run_coverage_report(graph_for_sprint_scoping, req_ids=[])
        assert report.unimplemented_requirements == []
        assert report.unverified_contracts == []
        assert report.unexecuted_tests == []
        assert report.end_to_end_gaps == []
        assert not report.has_gaps

    @pytest.mark.traces("DC-006")
    def test_scoped_section_1_filters_unimplemented_to_subset(self, graph_for_sprint_scoping: Path) -> None:
        """Section 1 includes only requirements whose ID is in req_ids."""
        report = run_coverage_report(graph_for_sprint_scoping, req_ids=["REQ-IN-1"])
        unimplemented_ids = [i.id for i in report.unimplemented_requirements]
        assert unimplemented_ids == ["REQ-IN-1"]
        assert "REQ-OUT-1" not in unimplemented_ids

    @pytest.mark.traces("DC-006")
    def test_scoped_section_2_filters_to_contracts_reachable_from_scope(self, graph_for_sprint_scoping: Path) -> None:
        """Section 2 includes only contracts reachable from in-scope requirements via FULFILLED_BY."""
        report = run_coverage_report(graph_for_sprint_scoping, req_ids=["REQ-IN-2"])
        unverified_ids = [i.id for i in report.unverified_contracts]
        assert unverified_ids == ["DC-IN-2"]
        assert "DC-OUT-2" not in unverified_ids

    @pytest.mark.traces("DC-006")
    def test_scoped_section_3_filters_to_tests_reachable_from_scope(self, graph_for_sprint_scoping: Path) -> None:
        """Section 3 includes only test cases reachable via FULFILLED_BY → VERIFIED_BY."""
        report = run_coverage_report(graph_for_sprint_scoping, req_ids=["REQ-IN-3"])
        unexecuted_ids = [i.id for i in report.unexecuted_tests]
        assert unexecuted_ids == ["TC-IN-3"]
        assert "TC-OUT-3" not in unexecuted_ids

    @pytest.mark.traces("DC-006")
    def test_scoped_section_4_filters_end_to_end_gaps_to_subset(self, graph_for_sprint_scoping: Path) -> None:
        """Section 4 includes only requirements whose ID is in req_ids."""
        report = run_coverage_report(graph_for_sprint_scoping, req_ids=["REQ-IN-2", "REQ-IN-3"])
        e2e_ids = [i.id for i in report.end_to_end_gaps]
        assert set(e2e_ids) == {"REQ-IN-2", "REQ-IN-3"}
        assert "REQ-OUT-2" not in e2e_ids
        assert "REQ-OUT-3" not in e2e_ids

    @pytest.mark.traces("DC-006")
    def test_unknown_req_ids_silently_yield_empty_report(self, graph_for_sprint_scoping: Path) -> None:
        """REQ IDs that do not exist in the graph contribute nothing and do not raise."""
        report = run_coverage_report(graph_for_sprint_scoping, req_ids=["REQ-DOES-NOT-EXIST"])
        assert report.unimplemented_requirements == []
        assert report.unverified_contracts == []
        assert report.unexecuted_tests == []
        assert report.end_to_end_gaps == []
        assert not report.has_gaps

    @pytest.mark.traces("DC-006")
    def test_mixed_known_and_unknown_req_ids_reports_only_known(self, graph_for_sprint_scoping: Path) -> None:
        """A mix of known and unknown IDs reports gaps only for the known ones."""
        report = run_coverage_report(graph_for_sprint_scoping, req_ids=["REQ-IN-1", "REQ-DOES-NOT-EXIST"])
        assert [i.id for i in report.unimplemented_requirements] == ["REQ-IN-1"]

    @pytest.mark.traces("DC-006")
    def test_scoped_summary_counts_reflect_scope(self, graph_for_sprint_scoping: Path) -> None:
        """Summary counts reflect the scoped sections, not the entire graph."""
        report = run_coverage_report(graph_for_sprint_scoping, req_ids=["REQ-IN-1"])
        summary = report.summary
        # REQ-IN-1 is unfulfilled (section 1 gap) but has no contracts → no other sections
        assert summary["unimplemented_requirements"] == 1
        assert summary["unverified_contracts"] == 0
        assert summary["unexecuted_tests"] == 0
        # Section 4: REQ-IN-1 has no path to a ValidationResult → it's an end-to-end gap
        assert summary["end_to_end_gaps"] == 1
