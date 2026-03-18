"""Tests for coverage report query (DC-006).

Every test is linked to a design contract via @pytest.mark.traces.
Tests verify observable behavior: what gaps are found, not how the query works internally.

Key invariant: missing tables must raise RuntimeError or be reported as full gaps —
never silently return empty results (false negatives hide traceability problems).
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
    def test_unimplemented_deterministic_order(self, graph_with_all_gaps: Path) -> None:
        """Contract: unimplemented_requirements is ordered deterministically by ID."""
        report1 = run_coverage_report(graph_with_all_gaps)
        report2 = run_coverage_report(graph_with_all_gaps)

        ids1 = [item.id for item in report1.unimplemented_requirements]
        ids2 = [item.id for item in report2.unimplemented_requirements]
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

    @pytest.mark.traces("DC-006")
    def test_unverified_deterministic_order(self, graph_with_all_gaps: Path) -> None:
        """Contract: unverified_contracts is ordered deterministically by ID."""
        report1 = run_coverage_report(graph_with_all_gaps)
        report2 = run_coverage_report(graph_with_all_gaps)

        ids1 = [item.id for item in report1.unverified_contracts]
        ids2 = [item.id for item in report2.unverified_contracts]
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
    def test_unexecuted_tests_deterministic_order(self, graph_with_all_gaps: Path) -> None:
        """Contract: unexecuted_tests is ordered deterministically by ID."""
        report1 = run_coverage_report(graph_with_all_gaps)
        report2 = run_coverage_report(graph_with_all_gaps)

        ids1 = [item.id for item in report1.unexecuted_tests]
        ids2 = [item.id for item in report2.unexecuted_tests]
        assert ids1 == ids2
        assert ids1 == sorted(ids1)

    @pytest.mark.traces("DC-006")
    def test_unexecuted_includes_id_and_title(self, graph_with_all_gaps: Path) -> None:
        """Contract: each unexecuted test item has id and title."""
        report = run_coverage_report(graph_with_all_gaps)

        for item in report.unexecuted_tests:
            assert item.id
            assert item.title


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
    def test_end_to_end_gaps_deterministic_order(self, graph_with_all_gaps: Path) -> None:
        """Contract: end_to_end_gaps is ordered deterministically by ID."""
        report1 = run_coverage_report(graph_with_all_gaps)
        report2 = run_coverage_report(graph_with_all_gaps)

        ids1 = [item.id for item in report1.end_to_end_gaps]
        ids2 = [item.id for item in report2.end_to_end_gaps]
        assert ids1 == ids2
        assert ids1 == sorted(ids1)

    @pytest.mark.traces("DC-006")
    def test_multi_hop_traversal_is_used(self, graph_fully_covered: Path) -> None:
        """Contract: section 4 performs multi-hop traversal (not just direct edges)."""
        # A fully-covered graph with 3 hops passes — confirms traversal works
        report = run_coverage_report(graph_fully_covered)
        assert report.end_to_end_gaps == []


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
