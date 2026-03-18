"""Tests for impact analysis query (DC-005).

Every test is linked to a design contract via @pytest.mark.traces.
Tests verify observable behavior: what connections are found, not how the query works internally.
"""

from __future__ import annotations

from pathlib import Path

import kuzu
import pytest

from scripts.query_impact import ImpactReport, query_impact

# --- Fixtures ---


@pytest.fixture()
def graph_with_all_edges(tmp_path: Path) -> Path:
    """Build a graph with VERIFIED_BY, FULFILLED_BY, and IMPACTS edges for DC-005."""
    db_path = tmp_path / "test_impact.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE VERIFIED_BY(FROM DesignContract TO TestCase, coverage STRING)")
    conn.execute("CREATE REL TABLE FULFILLED_BY(FROM Requirement TO DesignContract, completeness STRING)")
    conn.execute("CREATE REL TABLE IMPACTS(FROM DesignContract TO DesignContract, relationship STRING)")

    # Design contracts
    conn.execute("CREATE (n:DesignContract {id: 'DC-005', title: 'Impact Analysis', module: 'query_impact.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'CSV Validator', module: 'validate_csv.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-006', title: 'Coverage Report', module: 'query_coverage.py'})")

    # Test cases
    conn.execute(
        "CREATE (n:TestCase {id: 'TC-100', title: 'Impact Query Test A', pytest_path: 'tests/test_impact.py::test_a'})"
    )
    conn.execute(
        "CREATE (n:TestCase {id: 'TC-101', title: 'Impact Query Test B', pytest_path: 'tests/test_impact.py::test_b'})"
    )

    # Requirements
    conn.execute("CREATE (n:Requirement {id: 'REQ-006', title: 'Impact Analysis Requirement', priority: 'high'})")
    conn.execute("CREATE (n:Requirement {id: 'REQ-010', title: 'Self-Application Requirement', priority: 'must'})")

    # VERIFIED_BY edges: DC-005 → TC-100, TC-101
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-005' AND tc.id = 'TC-100' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'partial'}]->(tc)"
    )
    conn.execute(
        "MATCH (dc:DesignContract), (tc:TestCase) "
        "WHERE dc.id = 'DC-005' AND tc.id = 'TC-101' "
        "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
    )

    # FULFILLED_BY edges: REQ-006 → DC-005, REQ-010 → DC-005
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-006' AND dc.id = 'DC-005' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'full'}]->(dc)"
    )
    conn.execute(
        "MATCH (r:Requirement), (dc:DesignContract) "
        "WHERE r.id = 'REQ-010' AND dc.id = 'DC-005' "
        "CREATE (r)-[:FULFILLED_BY {completeness: 'partial'}]->(dc)"
    )

    # IMPACTS edges: DC-005 impacts DC-006 (outbound), DC-001 impacts DC-005 (inbound)
    conn.execute(
        "MATCH (a:DesignContract), (b:DesignContract) "
        "WHERE a.id = 'DC-005' AND b.id = 'DC-006' "
        "CREATE (a)-[:IMPACTS {relationship: 'depends_on'}]->(b)"
    )
    conn.execute(
        "MATCH (a:DesignContract), (b:DesignContract) "
        "WHERE a.id = 'DC-001' AND b.id = 'DC-005' "
        "CREATE (a)-[:IMPACTS {relationship: 'constrains'}]->(b)"
    )

    return db_path


@pytest.fixture()
def graph_no_edges(tmp_path: Path) -> Path:
    """Build a graph with a contract but no connecting edges."""
    db_path = tmp_path / "test_no_edges.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE Requirement(id STRING, title STRING, priority STRING, PRIMARY KEY (id))")
    conn.execute("CREATE REL TABLE VERIFIED_BY(FROM DesignContract TO TestCase, coverage STRING)")
    conn.execute("CREATE REL TABLE FULFILLED_BY(FROM Requirement TO DesignContract, completeness STRING)")
    conn.execute("CREATE REL TABLE IMPACTS(FROM DesignContract TO DesignContract, relationship STRING)")

    conn.execute("CREATE (n:DesignContract {id: 'DC-005', title: 'Impact Analysis', module: 'query_impact.py'})")

    return db_path


@pytest.fixture()
def graph_only_dc_table(tmp_path: Path) -> Path:
    """Build a graph with only DesignContract node table (no edge tables)."""
    db_path = tmp_path / "test_dc_only.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE (n:DesignContract {id: 'DC-005', title: 'Impact Analysis', module: 'query_impact.py'})")

    return db_path


# --- DC-005 Contract Tests ---


class TestQueryImpactDirectTests:
    """Tests for VERIFIED_BY edge traversal."""

    @pytest.mark.traces("DC-005")
    def test_finds_direct_tests(self, graph_with_all_edges: Path) -> None:
        """Contract: returns TestCase nodes connected via VERIFIED_BY edges."""
        report = query_impact(graph_with_all_edges, "DC-005")

        test_ids = [t.id for t in report.direct_tests]
        assert "TC-100" in test_ids
        assert "TC-101" in test_ids
        assert len(report.direct_tests) == 2

    @pytest.mark.traces("DC-005")
    def test_direct_tests_have_correct_edge_type(self, graph_with_all_edges: Path) -> None:
        """Contract: direct_tests items have edge_type VERIFIED_BY."""
        report = query_impact(graph_with_all_edges, "DC-005")

        for item in report.direct_tests:
            assert item.edge_type == "VERIFIED_BY"

    @pytest.mark.traces("DC-005")
    def test_direct_tests_ordered_by_id(self, graph_with_all_edges: Path) -> None:
        """Contract: direct_tests is ordered by TestCase ID."""
        report = query_impact(graph_with_all_edges, "DC-005")

        ids = [t.id for t in report.direct_tests]
        assert ids == sorted(ids)

    @pytest.mark.traces("DC-005")
    def test_empty_direct_tests_when_no_verified_by(self, graph_no_edges: Path) -> None:
        """Contract: direct_tests is empty when no VERIFIED_BY edges exist for contract."""
        report = query_impact(graph_no_edges, "DC-005")

        assert report.direct_tests == []

    @pytest.mark.traces("DC-005")
    def test_graceful_when_verified_by_table_missing(self, graph_only_dc_table: Path) -> None:
        """Contract: returns empty direct_tests when VERIFIED_BY table does not exist."""
        report = query_impact(graph_only_dc_table, "DC-005")

        assert report.direct_tests == []


class TestQueryImpactRequirements:
    """Tests for FULFILLED_BY edge traversal."""

    @pytest.mark.traces("DC-005")
    def test_finds_fulfilled_requirements(self, graph_with_all_edges: Path) -> None:
        """Contract: returns Requirement nodes connected via FULFILLED_BY edges."""
        report = query_impact(graph_with_all_edges, "DC-005")

        req_ids = [r.id for r in report.fulfilled_requirements]
        assert "REQ-006" in req_ids
        assert "REQ-010" in req_ids
        assert len(report.fulfilled_requirements) == 2

    @pytest.mark.traces("DC-005")
    def test_fulfilled_requirements_have_correct_edge_type(self, graph_with_all_edges: Path) -> None:
        """Contract: fulfilled_requirements items have edge_type FULFILLED_BY."""
        report = query_impact(graph_with_all_edges, "DC-005")

        for item in report.fulfilled_requirements:
            assert item.edge_type == "FULFILLED_BY"

    @pytest.mark.traces("DC-005")
    def test_fulfilled_requirements_inbound_direction(self, graph_with_all_edges: Path) -> None:
        """Contract: fulfilled_requirements items have inbound direction (Req → DC)."""
        report = query_impact(graph_with_all_edges, "DC-005")

        for item in report.fulfilled_requirements:
            assert item.direction == "inbound"

    @pytest.mark.traces("DC-005")
    def test_fulfilled_requirements_ordered_by_id(self, graph_with_all_edges: Path) -> None:
        """Contract: fulfilled_requirements is ordered by Requirement ID."""
        report = query_impact(graph_with_all_edges, "DC-005")

        ids = [r.id for r in report.fulfilled_requirements]
        assert ids == sorted(ids)

    @pytest.mark.traces("DC-005")
    def test_empty_requirements_when_no_fulfilled_by(self, graph_no_edges: Path) -> None:
        """Contract: fulfilled_requirements is empty when no FULFILLED_BY edges for contract."""
        report = query_impact(graph_no_edges, "DC-005")

        assert report.fulfilled_requirements == []

    @pytest.mark.traces("DC-005")
    def test_graceful_when_fulfilled_by_table_missing(self, graph_only_dc_table: Path) -> None:
        """Contract: returns empty fulfilled_requirements when FULFILLED_BY table does not exist."""
        report = query_impact(graph_only_dc_table, "DC-005")

        assert report.fulfilled_requirements == []


class TestQueryImpactedContracts:
    """Tests for IMPACTS edge traversal (both directions)."""

    @pytest.mark.traces("DC-005")
    def test_finds_outbound_impacts(self, graph_with_all_edges: Path) -> None:
        """Contract: returns contracts this contract impacts (outbound IMPACTS edge)."""
        report = query_impact(graph_with_all_edges, "DC-005")

        outbound = [c for c in report.impacted_contracts if c.direction == "outbound"]
        outbound_ids = [c.id for c in outbound]
        assert "DC-006" in outbound_ids

    @pytest.mark.traces("DC-005")
    def test_finds_inbound_impacts(self, graph_with_all_edges: Path) -> None:
        """Contract: returns contracts that impact this contract (inbound IMPACTS edge)."""
        report = query_impact(graph_with_all_edges, "DC-005")

        inbound = [c for c in report.impacted_contracts if c.direction == "inbound"]
        inbound_ids = [c.id for c in inbound]
        assert "DC-001" in inbound_ids

    @pytest.mark.traces("DC-005")
    def test_impacted_contracts_have_correct_edge_type(self, graph_with_all_edges: Path) -> None:
        """Contract: impacted_contracts items have edge_type IMPACTS."""
        report = query_impact(graph_with_all_edges, "DC-005")

        for item in report.impacted_contracts:
            assert item.edge_type == "IMPACTS"

    @pytest.mark.traces("DC-005")
    def test_empty_impacted_contracts_when_no_impacts(self, graph_no_edges: Path) -> None:
        """Contract: impacted_contracts is empty when no IMPACTS edges exist for contract."""
        report = query_impact(graph_no_edges, "DC-005")

        assert report.impacted_contracts == []

    @pytest.mark.traces("DC-005")
    def test_graceful_when_impacts_table_missing(self, graph_only_dc_table: Path) -> None:
        """Contract: returns empty impacted_contracts when IMPACTS table does not exist."""
        report = query_impact(graph_only_dc_table, "DC-005")

        assert report.impacted_contracts == []


class TestQueryImpactReport:
    """Tests for full ImpactReport structure."""

    @pytest.mark.traces("DC-005")
    def test_report_has_contract_metadata(self, graph_with_all_edges: Path) -> None:
        """Contract: report includes contract_id and contract_title."""
        report = query_impact(graph_with_all_edges, "DC-005")

        assert report.contract_id == "DC-005"
        assert report.contract_title == "Impact Analysis"

    @pytest.mark.traces("DC-005")
    def test_total_connections_counts_all_edges(self, graph_with_all_edges: Path) -> None:
        """Contract: total_connections sums all edge types."""
        report = query_impact(graph_with_all_edges, "DC-005")

        # 2 tests + 2 requirements + 2 impacts = 6
        assert report.total_connections == 6

    @pytest.mark.traces("DC-005")
    def test_total_connections_zero_when_no_edges(self, graph_no_edges: Path) -> None:
        """Contract: total_connections is 0 when no edges exist."""
        report = query_impact(graph_no_edges, "DC-005")

        assert report.total_connections == 0

    @pytest.mark.traces("DC-005")
    def test_full_report_type(self, graph_with_all_edges: Path) -> None:
        """Contract: query_impact returns an ImpactReport instance."""
        report = query_impact(graph_with_all_edges, "DC-005")

        assert isinstance(report, ImpactReport)


class TestQueryImpactErrorSemantics:
    """Tests for error conditions per DC-005 error semantics."""

    @pytest.mark.traces("DC-005")
    def test_missing_db_raises_file_not_found(self, tmp_path: Path) -> None:
        """Contract: raises FileNotFoundError when database path doesn't exist."""
        with pytest.raises(FileNotFoundError):
            query_impact(tmp_path / "nonexistent.kuzu", "DC-005")

    @pytest.mark.traces("DC-005")
    def test_missing_schema_raises_runtime_error(self, tmp_path: Path) -> None:
        """Contract: raises RuntimeError when DesignContract table is missing."""
        db_path = tmp_path / "empty.kuzu"
        db = kuzu.Database(str(db_path))
        kuzu.Connection(db)

        with pytest.raises(RuntimeError, match="Missing required tables"):
            query_impact(db_path, "DC-005")

    @pytest.mark.traces("DC-005")
    def test_missing_contract_id_raises_value_error(self, graph_with_all_edges: Path) -> None:
        """Contract: raises ValueError when contract_id not found in database."""
        with pytest.raises(ValueError, match="DesignContract not found"):
            query_impact(graph_with_all_edges, "DC-999")


class TestQueryImpactSelfApplication:
    """Test DC-005 against the project's own traceability graph."""

    @pytest.mark.traces("DC-005")
    def test_project_impact_analysis_runs(self, tmp_path: Path) -> None:
        """Contract: impact analysis runs against the project's own graph."""
        from scripts.build_graph import build_graph

        project_root = Path(__file__).parent.parent
        build_report = build_graph(
            csv_dir=project_root / "traceability",
            schema_dir=project_root / "schemas",
            output_path=tmp_path / "project.kuzu",
        )
        assert build_report.success

        db_path = tmp_path / "project.kuzu"

        # DC-001 has VERIFIED_BY edges and FULFILLED_BY edges in the project CSVs
        report = query_impact(db_path, "DC-001")
        assert isinstance(report, ImpactReport)
        assert report.contract_id == "DC-001"
        # DC-001 is linked to TC-001 through TC-008 via VERIFIED_BY
        assert len(report.direct_tests) > 0
        # REQ-012 is fulfilled by DC-001 via FULFILLED_BY
        assert len(report.fulfilled_requirements) > 0

    @pytest.mark.traces("DC-005")
    def test_project_dc005_not_found_raises(self, tmp_path: Path) -> None:
        """Contract: querying nonexistent contract in project graph raises ValueError."""
        from scripts.build_graph import build_graph

        project_root = Path(__file__).parent.parent
        build_report = build_graph(
            csv_dir=project_root / "traceability",
            schema_dir=project_root / "schemas",
            output_path=tmp_path / "project2.kuzu",
        )
        assert build_report.success

        with pytest.raises(ValueError, match="DesignContract not found"):
            query_impact(tmp_path / "project2.kuzu", "DC-999")
