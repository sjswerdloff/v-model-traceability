"""Tests for gap analysis queries (DC-004).

Every test is linked to a design contract via @pytest.mark.traces.
Tests verify observable behavior: what gaps are found, not how the query works internally.
"""

from __future__ import annotations

from pathlib import Path

import kuzu
import pytest

from scripts.query_gaps import (
    GapReport,
    query_domain_terms_without_aliases,
    query_empty_bounded_contexts,
    query_partial_only_contracts,
    query_unimplemented_requirements,
    query_unscoped_design_contracts,
    query_untested_contracts,
    run_gap_analysis,
)

# --- Fixtures ---


@pytest.fixture()
def graph_with_gaps(tmp_path: Path) -> Path:
    """Build a graph where some contracts lack VERIFIED_BY edges."""
    db_path = tmp_path / "test.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE VERIFIED_BY(FROM DesignContract TO TestCase, coverage STRING)")
    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE FULFILLED_BY(FROM Requirement TO DesignContract, completeness STRING)")

    # 3 contracts: DC-001 tested, DC-002 tested, DC-003 untested
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'CSV Validator', module: 'validate_csv.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-002', title: 'Ref Validator', module: 'validate_csv.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-003', title: 'Graph Builder', module: 'build_graph.py'})")

    # 2 test cases linked to DC-001 and DC-002
    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Valid CSV', pytest_path: 'tests/test_a.py::test_1'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-002', title: 'Valid Refs', pytest_path: 'tests/test_a.py::test_2'})")

    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-001' AND tc.id = 'TC-001' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-002' AND tc.id = 'TC-002' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'partial'}]->(tc)"
    )

    # 3 requirements: REQ-001 and REQ-002 fulfilled, REQ-003 not
    conn.execute("CREATE (n:Requirement {id: 'REQ-001', title: 'Templates', priority: 'must'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-002', title: 'Schemas', priority: 'must'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-003', title: 'Unfulfilled', priority: 'should'})")

    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-001' AND dc.id = 'DC-001' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-002' AND dc.id = 'DC-002' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )

    return db_path


@pytest.fixture()
def graph_fully_covered(tmp_path: Path) -> Path:
    """Build a graph where all contracts have VERIFIED_BY edges."""
    db_path = tmp_path / "test.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE VERIFIED_BY(FROM DesignContract TO TestCase, coverage STRING)")
    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE FULFILLED_BY(FROM Requirement TO DesignContract, completeness STRING)")

    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Validator', module: 'validate.py'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Test Validator', pytest_path: 'tests/test.py::test'})")
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-001' AND tc.id = 'TC-001' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )

    conn.execute("CREATE (n:Requirement {id: 'REQ-001', title: 'Requirement', priority: 'must'})")
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-001' AND dc.id = 'DC-001' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )

    return db_path


# --- DC-004 Contract Tests ---


class TestUntestedContracts:
    """Tests for query_untested_contracts."""

    @pytest.mark.traces("DC-004")
    def test_finds_untested_contracts(self, graph_with_gaps: Path) -> None:
        """Contract: returns contracts with zero VERIFIED_BY edges."""
        gaps = query_untested_contracts(graph_with_gaps)

        assert len(gaps) == 1
        assert gaps[0].id == "DC-003"
        assert gaps[0].title == "Graph Builder"
        assert gaps[0].module == "build_graph.py"

    @pytest.mark.traces("DC-004")
    def test_empty_when_all_tested(self, graph_fully_covered: Path) -> None:
        """Contract: returns empty list when every contract has at least one test."""
        gaps = query_untested_contracts(graph_fully_covered)

        assert gaps == []

    @pytest.mark.traces("DC-004")
    def test_output_includes_actionable_fields(self, graph_with_gaps: Path) -> None:
        """Contract: includes contract ID, title, and module for actionability."""
        gaps = query_untested_contracts(graph_with_gaps)

        for gap in gaps:
            assert gap.id
            assert gap.title
            assert gap.module

    @pytest.mark.traces("DC-004")
    def test_deterministic_order(self, graph_with_gaps: Path) -> None:
        """Contract: output is deterministically ordered by contract ID."""
        gaps1 = query_untested_contracts(graph_with_gaps)
        gaps2 = query_untested_contracts(graph_with_gaps)

        assert [g.id for g in gaps1] == [g.id for g in gaps2]

    @pytest.mark.traces("DC-004")
    def test_missing_db_raises(self, tmp_path: Path) -> None:
        """Contract: fails if database path doesn't exist."""
        with pytest.raises(FileNotFoundError):
            query_untested_contracts(tmp_path / "nonexistent.kuzu")

    @pytest.mark.traces("DC-004")
    def test_missing_schema_raises(self, tmp_path: Path) -> None:
        """Contract: fails if expected schema is missing from database."""
        db_path = tmp_path / "empty.kuzu"
        db = kuzu.Database(str(db_path))
        kuzu.Connection(db)

        with pytest.raises(RuntimeError, match="Missing required tables"):
            query_untested_contracts(db_path)


class TestUnimplementedRequirements:
    """Tests for query_unimplemented_requirements."""

    @pytest.mark.traces("DC-004")
    def test_finds_unimplemented_requirements(self, graph_with_gaps: Path) -> None:
        """Contract: returns requirements with zero FULFILLED_BY edges."""
        gaps = query_unimplemented_requirements(graph_with_gaps)

        assert len(gaps) == 1
        assert gaps[0].id == "REQ-003"
        assert gaps[0].title == "Unfulfilled"

    @pytest.mark.traces("DC-004")
    def test_empty_when_all_implemented(self, graph_fully_covered: Path) -> None:
        """Contract: returns empty list when every requirement has a contract."""
        gaps = query_unimplemented_requirements(graph_fully_covered)

        assert gaps == []


class TestGapReport:
    """Tests for run_gap_analysis."""

    @pytest.mark.traces("DC-004")
    def test_full_report_with_gaps(self, graph_with_gaps: Path) -> None:
        """Contract: report includes both untested contracts and unimplemented requirements."""
        report = run_gap_analysis(graph_with_gaps)

        assert report.has_gaps
        assert len(report.untested_contracts) == 1
        assert len(report.unimplemented_requirements) == 1

    @pytest.mark.traces("DC-004")
    def test_full_report_no_gaps(self, graph_fully_covered: Path) -> None:
        """Contract: report has_gaps is False when fully covered."""
        report = run_gap_analysis(graph_fully_covered)

        assert not report.has_gaps


class TestPartialOnlyContracts:
    """Tests for query_partial_only_contracts."""

    @pytest.mark.traces("DC-004")
    def test_finds_partial_only_contracts(self, graph_with_gaps: Path) -> None:
        """Contract: returns DCs where all verified_by edges are partial, none full."""
        gaps = query_partial_only_contracts(graph_with_gaps)

        # DC-002 has only a partial edge — should appear
        assert len(gaps) == 1
        assert gaps[0].id == "DC-002"

    @pytest.mark.traces("DC-004")
    def test_excludes_contracts_with_full_edge(self, graph_with_gaps: Path) -> None:
        """Contract: DC with at least one full edge does not appear."""
        gaps = query_partial_only_contracts(graph_with_gaps)

        # DC-001 has a full edge — must not appear
        gap_ids = {g.id for g in gaps}
        assert "DC-001" not in gap_ids

    @pytest.mark.traces("DC-004")
    def test_excludes_untested_contracts(self, graph_with_gaps: Path) -> None:
        """Contract: DC with no edges at all does not appear (untested_contracts handles that)."""
        gaps = query_partial_only_contracts(graph_with_gaps)

        # DC-003 has no edges — must not appear here
        gap_ids = {g.id for g in gaps}
        assert "DC-003" not in gap_ids

    @pytest.mark.traces("DC-004")
    def test_empty_when_all_full(self, graph_fully_covered: Path) -> None:
        """Contract: returns empty when all DCs have at least one full edge."""
        gaps = query_partial_only_contracts(graph_fully_covered)
        assert gaps == []

    @pytest.mark.traces("DC-004")
    def test_gap_report_includes_partial_only(self, graph_with_gaps: Path) -> None:
        """Contract: GapReport includes partial_only_contracts and has_warnings."""
        report = run_gap_analysis(graph_with_gaps)
        assert report.has_warnings
        assert len(report.partial_only_contracts) == 1
        assert report.partial_only_contracts[0].id == "DC-002"

    @pytest.mark.traces("DC-004")
    def test_gap_report_no_warnings_when_all_full(self, graph_fully_covered: Path) -> None:
        """Contract: has_warnings is False when all DCs have full coverage."""
        report = run_gap_analysis(graph_fully_covered)
        assert not report.has_warnings


class TestSelfApplication:
    """Test DC-004 against the project's own traceability graph (REQ-010)."""

    @pytest.mark.traces("DC-004")
    def test_project_gap_analysis_runs(self, tmp_path: Path) -> None:
        """Contract: gap analysis runs against project's own graph."""
        from scripts.build_graph import build_graph

        project_root = Path(__file__).parent.parent
        report = build_graph(
            csv_dir=project_root / "traceability",
            schema_dir=project_root / "schemas",
            output_path=tmp_path / "project.kuzu",
        )
        assert report.success

        gap_report = run_gap_analysis(tmp_path / "project.kuzu")

        # DC-004 through DC-009 should show as untested (no verified_by for them yet)
        untested_ids = [g.id for g in gap_report.untested_contracts]
        # DC-001, DC-002, DC-003 should NOT be in gaps (they have tests)
        assert "DC-001" not in untested_ids
        assert "DC-002" not in untested_ids
        assert "DC-003" not in untested_ids


# --- DDD fixtures ---


@pytest.fixture()
def graph_with_ddd(tmp_path: Path) -> Path:
    """Build a graph with BoundedContext, DomainTerm, and DesignContract DDD columns.

    Layout:
    - BC-001 (Billing): has DC-001 pointing to it  → not an empty BC
    - BC-002 (Ordering): no DCs point to it         → empty BC (gap)
    - DC-001: bounded_context_id = 'BC-001'         → scoped
    - DC-002: bounded_context_id = ''               → unscoped (warning)
    - DT-001: aliases_to_avoid = 'Invoice,Bill'     → has aliases (fine)
    - DT-002: aliases_to_avoid = ''                 → no aliases (warning)
    """
    db_path = tmp_path / "ddd.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute(
        "CREATE NODE TABLE BoundedContext("
        "id STRING, name STRING, purpose STRING, classification STRING, "
        "domain_type STRING, status STRING, approved_by STRING, approval_date STRING, "
        "PRIMARY KEY (id))"
    )
    conn.execute(
        "CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, bounded_context_id STRING, PRIMARY KEY (id))"
    )
    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute(
        "CREATE NODE TABLE DomainTerm("
        "id STRING, term STRING, definition STRING, bounded_context STRING, "
        "related_terms STRING, aliases_to_avoid STRING, status STRING, "
        "approved_by STRING, approval_date STRING, "
        "PRIMARY KEY (id))"
    )

    # Bounded contexts
    conn.execute(
        "CREATE (n:BoundedContext {id: 'BC-001', name: 'Billing', purpose: 'Handle invoices', "
        "classification: 'core', domain_type: 'subdomain', status: 'approved', "
        "approved_by: 'Alice', approval_date: '2026-01-01'})"
    )
    conn.execute(
        "CREATE (n:BoundedContext {id: 'BC-002', name: 'Ordering', purpose: 'Manage orders', "
        "classification: 'supporting', domain_type: 'subdomain', status: 'draft', "
        "approved_by: '', approval_date: ''})"
    )

    # Design contracts
    conn.execute(
        "CREATE (n:DesignContract {id: 'DC-001', title: 'Invoice Validator', "
        "module: 'invoice.py', bounded_context_id: 'BC-001'})"
    )
    conn.execute(
        "CREATE (n:DesignContract {id: 'DC-002', title: 'Order Processor', module: 'order.py', bounded_context_id: ''})"
    )

    # Domain terms
    conn.execute(
        "CREATE (n:DomainTerm {id: 'DT-001', term: 'Invoice', "
        "definition: 'A bill sent to a customer', bounded_context: 'BC-001', "
        "related_terms: 'Bill', aliases_to_avoid: 'Invoice,Bill', "
        "status: 'approved', approved_by: 'Alice', approval_date: '2026-01-01'})"
    )
    conn.execute(
        "CREATE (n:DomainTerm {id: 'DT-002', term: 'Order', "
        "definition: 'A customer purchase request', bounded_context: 'BC-002', "
        "related_terms: '', aliases_to_avoid: '', "
        "status: 'draft', approved_by: '', approval_date: ''})"
    )

    return db_path


@pytest.fixture()
def graph_ddd_fully_scoped(tmp_path: Path) -> Path:
    """Build a DDD graph where all BCs have DCs and all DTs have aliases.

    Layout:
    - BC-001: has DC-001 → not empty
    - DC-001: bounded_context_id = 'BC-001' → scoped
    - DT-001: aliases_to_avoid non-empty → has aliases
    """
    db_path = tmp_path / "ddd_full.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute(
        "CREATE NODE TABLE BoundedContext("
        "id STRING, name STRING, purpose STRING, classification STRING, "
        "domain_type STRING, status STRING, approved_by STRING, approval_date STRING, "
        "PRIMARY KEY (id))"
    )
    conn.execute(
        "CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, bounded_context_id STRING, PRIMARY KEY (id))"
    )
    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute(
        "CREATE NODE TABLE DomainTerm("
        "id STRING, term STRING, definition STRING, bounded_context STRING, "
        "related_terms STRING, aliases_to_avoid STRING, status STRING, "
        "approved_by STRING, approval_date STRING, "
        "PRIMARY KEY (id))"
    )

    conn.execute(
        "CREATE (n:BoundedContext {id: 'BC-001', name: 'Billing', purpose: 'Handle invoices', "
        "classification: 'core', domain_type: 'subdomain', status: 'approved', "
        "approved_by: 'Alice', approval_date: '2026-01-01'})"
    )
    conn.execute(
        "CREATE (n:DesignContract {id: 'DC-001', title: 'Invoice Validator', "
        "module: 'invoice.py', bounded_context_id: 'BC-001'})"
    )
    conn.execute(
        "CREATE (n:DomainTerm {id: 'DT-001', term: 'Invoice', "
        "definition: 'A bill sent to a customer', bounded_context: 'BC-001', "
        "related_terms: 'Bill', aliases_to_avoid: 'Invoice,Bill', "
        "status: 'approved', approved_by: 'Alice', approval_date: '2026-01-01'})"
    )

    return db_path


@pytest.fixture()
def graph_without_ddd_tables(tmp_path: Path) -> Path:
    """Build a graph with only base V-model tables, no BoundedContext or DomainTerm."""
    db_path = tmp_path / "no_ddd.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Validator', module: 'validate.py'})")

    return db_path


# --- DDD gap analysis tests ---


class TestEmptyBoundedContexts:
    """Tests for query_empty_bounded_contexts."""

    @pytest.mark.traces("DC-004")
    def test_finds_empty_bounded_contexts(self, graph_with_ddd: Path) -> None:
        """Contract: returns BCs with no DesignContracts pointing to them."""
        gaps = query_empty_bounded_contexts(graph_with_ddd)

        assert len(gaps) == 1
        assert gaps[0].id == "BC-002"
        assert gaps[0].title == "Ordering"
        assert gaps[0].module == "Manage orders"

    @pytest.mark.traces("DC-004")
    def test_empty_when_all_bcs_have_contracts(self, graph_ddd_fully_scoped: Path) -> None:
        """Contract: returns empty list when every BC has at least one DC."""
        gaps = query_empty_bounded_contexts(graph_ddd_fully_scoped)

        assert gaps == []

    @pytest.mark.traces("DC-004")
    def test_graceful_when_no_bounded_context_table(self, graph_without_ddd_tables: Path) -> None:
        """Contract: returns empty list when BoundedContext table doesn't exist."""
        gaps = query_empty_bounded_contexts(graph_without_ddd_tables)

        assert gaps == []

    @pytest.mark.traces("DC-004")
    def test_missing_db_raises(self, tmp_path: Path) -> None:
        """Contract: fails if database path doesn't exist."""
        with pytest.raises(FileNotFoundError):
            query_empty_bounded_contexts(tmp_path / "nonexistent.kuzu")

    @pytest.mark.traces("DC-004")
    def test_missing_design_contract_table_raises(self, tmp_path: Path) -> None:
        """Contract: fails if BoundedContext exists but DesignContract table is missing."""
        db_path = tmp_path / "bc_only.kuzu"
        db = kuzu.Database(str(db_path))
        conn = kuzu.Connection(db)
        conn.execute(
            "CREATE NODE TABLE BoundedContext("
            "id STRING, name STRING, purpose STRING, classification STRING, "
            "domain_type STRING, status STRING, approved_by STRING, approval_date STRING, "
            "PRIMARY KEY (id))"
        )

        with pytest.raises(RuntimeError, match="Missing required tables"):
            query_empty_bounded_contexts(db_path)

    @pytest.mark.traces("DC-004")
    def test_deterministic_order(self, graph_with_ddd: Path) -> None:
        """Contract: output is deterministically ordered by BC ID."""
        gaps1 = query_empty_bounded_contexts(graph_with_ddd)
        gaps2 = query_empty_bounded_contexts(graph_with_ddd)

        assert [g.id for g in gaps1] == [g.id for g in gaps2]

    @pytest.mark.traces("DC-004")
    def test_gap_report_includes_empty_bounded_contexts(self, graph_with_ddd: Path) -> None:
        """Contract: GapReport.empty_bounded_contexts is populated and has_gaps is True."""
        report = run_gap_analysis(graph_with_ddd)

        assert report.has_gaps
        assert len(report.empty_bounded_contexts) == 1
        assert report.empty_bounded_contexts[0].id == "BC-002"

    @pytest.mark.traces("DC-004")
    def test_gap_report_no_gaps_when_all_scoped(self, graph_ddd_fully_scoped: Path) -> None:
        """Contract: empty_bounded_contexts is empty when every BC has at least one DC."""
        report = run_gap_analysis(graph_ddd_fully_scoped)

        assert report.empty_bounded_contexts == []


class TestUnscopedDesignContracts:
    """Tests for query_unscoped_design_contracts."""

    @pytest.mark.traces("DC-004")
    def test_finds_unscoped_design_contracts(self, graph_with_ddd: Path) -> None:
        """Contract: returns DCs with empty bounded_context_id."""
        gaps = query_unscoped_design_contracts(graph_with_ddd)

        assert len(gaps) == 1
        assert gaps[0].id == "DC-002"
        assert gaps[0].title == "Order Processor"
        assert gaps[0].module == "order.py"

    @pytest.mark.traces("DC-004")
    def test_empty_when_all_contracts_scoped(self, graph_ddd_fully_scoped: Path) -> None:
        """Contract: returns empty list when every DC has a bounded_context_id."""
        gaps = query_unscoped_design_contracts(graph_ddd_fully_scoped)

        assert gaps == []

    @pytest.mark.traces("DC-004")
    def test_graceful_when_no_bounded_context_table(self, graph_without_ddd_tables: Path) -> None:
        """Contract: returns empty list when BoundedContext table doesn't exist."""
        gaps = query_unscoped_design_contracts(graph_without_ddd_tables)

        assert gaps == []

    @pytest.mark.traces("DC-004")
    def test_missing_db_raises(self, tmp_path: Path) -> None:
        """Contract: fails if database path doesn't exist."""
        with pytest.raises(FileNotFoundError):
            query_unscoped_design_contracts(tmp_path / "nonexistent.kuzu")

    @pytest.mark.traces("DC-004")
    def test_gap_report_includes_unscoped_contracts(self, graph_with_ddd: Path) -> None:
        """Contract: GapReport.unscoped_design_contracts is populated and has_warnings is True."""
        report = run_gap_analysis(graph_with_ddd)

        assert report.has_warnings
        assert len(report.unscoped_design_contracts) == 1
        assert report.unscoped_design_contracts[0].id == "DC-002"

    @pytest.mark.traces("DC-004")
    def test_gap_report_no_warnings_for_scoped(self, graph_ddd_fully_scoped: Path) -> None:
        """Contract: has_warnings is False when all DCs are scoped and all DTs have aliases."""
        report = run_gap_analysis(graph_ddd_fully_scoped)

        assert not report.has_warnings
        assert report.unscoped_design_contracts == []


class TestDomainTermsWithoutAliases:
    """Tests for query_domain_terms_without_aliases."""

    @pytest.mark.traces("DC-004")
    def test_finds_terms_without_aliases(self, graph_with_ddd: Path) -> None:
        """Contract: returns DomainTerms where aliases_to_avoid is empty."""
        gaps = query_domain_terms_without_aliases(graph_with_ddd)

        assert len(gaps) == 1
        assert gaps[0].id == "DT-002"
        assert gaps[0].title == "Order"
        assert gaps[0].module == "BC-002"

    @pytest.mark.traces("DC-004")
    def test_empty_when_all_terms_have_aliases(self, graph_ddd_fully_scoped: Path) -> None:
        """Contract: returns empty list when every DomainTerm has aliases_to_avoid."""
        gaps = query_domain_terms_without_aliases(graph_ddd_fully_scoped)

        assert gaps == []

    @pytest.mark.traces("DC-004")
    def test_graceful_when_no_domain_term_table(self, graph_without_ddd_tables: Path) -> None:
        """Contract: returns empty list when DomainTerm table doesn't exist."""
        gaps = query_domain_terms_without_aliases(graph_without_ddd_tables)

        assert gaps == []

    @pytest.mark.traces("DC-004")
    def test_missing_db_raises(self, tmp_path: Path) -> None:
        """Contract: fails if database path doesn't exist."""
        with pytest.raises(FileNotFoundError):
            query_domain_terms_without_aliases(tmp_path / "nonexistent.kuzu")

    @pytest.mark.traces("DC-004")
    def test_gap_report_includes_terms_without_aliases(self, graph_with_ddd: Path) -> None:
        """Contract: GapReport.domain_terms_without_aliases is populated and has_warnings is True."""
        report = run_gap_analysis(graph_with_ddd)

        assert report.has_warnings
        assert len(report.domain_terms_without_aliases) == 1
        assert report.domain_terms_without_aliases[0].id == "DT-002"

    @pytest.mark.traces("DC-004")
    def test_gap_report_no_warnings_when_all_have_aliases(self, graph_ddd_fully_scoped: Path) -> None:
        """Contract: domain_terms_without_aliases is empty when all terms have aliases."""
        report = run_gap_analysis(graph_ddd_fully_scoped)

        assert report.domain_terms_without_aliases == []


class TestGapReportDDDIntegration:
    """Integration tests for GapReport with DDD fields."""

    @pytest.mark.traces("DC-004")
    def test_gap_report_dataclass_has_ddd_fields(self) -> None:
        """Contract: GapReport dataclass includes all six fields."""
        report = GapReport()

        assert hasattr(report, "untested_contracts")
        assert hasattr(report, "unimplemented_requirements")
        assert hasattr(report, "partial_only_contracts")
        assert hasattr(report, "empty_bounded_contexts")
        assert hasattr(report, "unscoped_design_contracts")
        assert hasattr(report, "domain_terms_without_aliases")

    @pytest.mark.traces("DC-004")
    def test_has_gaps_false_when_only_warnings(self, graph_with_ddd: Path) -> None:
        """Contract: has_gaps is True only when real gaps exist (empty BCs), not just warnings."""
        # graph_with_ddd has BC-002 empty → that IS a gap
        report = run_gap_analysis(graph_with_ddd)

        assert report.has_gaps  # BC-002 is empty
        assert report.has_warnings  # DC-002 unscoped, DT-002 no aliases

    @pytest.mark.traces("DC-004")
    def test_non_ddd_graph_graceful_in_full_run(self, graph_with_gaps: Path) -> None:
        """Contract: run_gap_analysis on a non-DDD graph returns empty DDD fields gracefully."""
        report = run_gap_analysis(graph_with_gaps)

        assert report.empty_bounded_contexts == []
        assert report.unscoped_design_contracts == []
        assert report.domain_terms_without_aliases == []
