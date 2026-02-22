"""Tests for Graph Build Pipeline (DC-003).

Every test is linked to a design contract via @pytest.mark.traces.
Tests verify observable behavior (what the module accomplishes),
not implementation details.
"""

from __future__ import annotations

from pathlib import Path

import kuzu
import pytest

from scripts.build_graph import BuildReport, build_graph


def _query_to_dicts(conn: kuzu.Connection, query: str) -> list[dict[str, str]]:
    """Execute a Kuzu query and return results as list of dicts.

    Uses native kuzu iteration to avoid polars/pandas dependency.
    """
    result = conn.execute(query)
    columns = result.get_column_names()
    rows = []
    while result.has_next():
        values = result.get_next()
        rows.append(dict(zip(columns, values)))
    return rows


# --- Fixtures ---


@pytest.fixture()
def project_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create csv_dir, schema_dir (with nodes/ and edges/ subdirs), and output_path."""
    csv_dir = tmp_path / "traceability"
    schema_dir = tmp_path / "schemas"
    output_path = tmp_path / "test_db"

    csv_dir.mkdir()
    (schema_dir / "nodes").mkdir(parents=True)
    (schema_dir / "edges").mkdir(parents=True)

    return csv_dir, schema_dir, output_path


@pytest.fixture()
def populated_dirs(project_dirs: tuple[Path, Path, Path]) -> tuple[Path, Path, Path]:
    """Create a minimal valid dataset with 2 node types and 1 edge type."""
    csv_dir, schema_dir, output_path = project_dirs

    # Node schema: requirement
    (schema_dir / "nodes" / "requirement.csvschema").write_text(
        "# Requirement node schema\n"
        "# id_field: id\n"
        "# csv_file: requirements.csv\n"
        "id,title,status\n"
    )
    # Node schema: design_contract
    (schema_dir / "nodes" / "design_contract.csvschema").write_text(
        "# DesignContract node schema\n"
        "# id_field: id\n"
        "# csv_file: design_contracts.csv\n"
        "id,title,module,status\n"
    )
    # Edge schema: fulfilled_by
    (schema_dir / "edges" / "fulfilled_by.csvschema").write_text(
        "# FULFILLED_BY edge schema\n"
        "# references: requirement_id -> requirement, design_contract_id -> design_contract\n"
        "# csv_file: fulfilled_by.csv\n"
        "requirement_id,design_contract_id,completeness\n"
    )

    # Node CSVs
    (csv_dir / "requirements.csv").write_text(
        "id,title,status\n"
        "REQ-001,First Requirement,draft\n"
        "REQ-002,Second Requirement,approved\n"
    )
    (csv_dir / "design_contracts.csv").write_text(
        "id,title,module,status\n"
        "DC-001,First Contract,mod_a.py,draft\n"
    )
    # Edge CSV
    (csv_dir / "fulfilled_by.csv").write_text(
        "requirement_id,design_contract_id,completeness\n"
        "REQ-001,DC-001,full\n"
    )

    return csv_dir, schema_dir, output_path


# --- DC-003: Graph Build Pipeline Tests ---


class TestBuildGraph:
    """Tests for DC-003: Graph Build Pipeline."""

    @pytest.mark.traces("DC-003")
    def test_builds_database_from_valid_csvs(
        self, populated_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Valid CSVs produce a Kuzu database with correct node and edge counts."""
        csv_dir, schema_dir, output_path = populated_dirs

        report = build_graph(csv_dir, schema_dir, output_path)

        assert report.success is True
        assert report.validation_errors == []
        assert output_path.exists()
        assert report.tables_created["Requirement"] == 2
        assert report.tables_created["DesignContract"] == 1
        assert report.tables_created["FULFILLED_BY"] == 1

    @pytest.mark.traces("DC-003")
    def test_node_data_queryable(
        self, populated_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Built graph has queryable nodes with correct property values."""
        csv_dir, schema_dir, output_path = populated_dirs

        build_graph(csv_dir, schema_dir, output_path)

        db = kuzu.Database(str(output_path))
        conn = kuzu.Connection(db)
        rows = _query_to_dicts(conn, "MATCH (r:Requirement) RETURN r.id, r.title ORDER BY r.id")

        assert len(rows) == 2
        assert rows[0]["r.id"] == "REQ-001"
        assert rows[1]["r.title"] == "Second Requirement"

    @pytest.mark.traces("DC-003")
    def test_edge_data_queryable(
        self, populated_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Built graph has queryable edges connecting correct nodes."""
        csv_dir, schema_dir, output_path = populated_dirs

        build_graph(csv_dir, schema_dir, output_path)

        db = kuzu.Database(str(output_path))
        conn = kuzu.Connection(db)
        rows = _query_to_dicts(
            conn,
            "MATCH (r:Requirement)-[f:FULFILLED_BY]->(d:DesignContract) "
            "RETURN r.id, d.id, f.completeness",
        )

        assert len(rows) == 1
        assert rows[0]["r.id"] == "REQ-001"
        assert rows[0]["d.id"] == "DC-001"
        assert rows[0]["f.completeness"] == "full"

    @pytest.mark.traces("DC-003")
    def test_idempotent_rebuild(
        self, populated_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Running build twice produces identical graph (idempotent)."""
        csv_dir, schema_dir, output_path = populated_dirs

        report1 = build_graph(csv_dir, schema_dir, output_path)
        report2 = build_graph(csv_dir, schema_dir, output_path)

        assert report1.success is True
        assert report2.success is True
        assert report1.tables_created == report2.tables_created

        # Verify data is correct after rebuild
        db = kuzu.Database(str(output_path))
        conn = kuzu.Connection(db)
        rows = _query_to_dicts(conn, "MATCH (r:Requirement) RETURN count(r.id) AS cnt")

        assert rows[0]["cnt"] == 2

    @pytest.mark.traces("DC-003")
    def test_validation_failure_prevents_build(
        self, project_dirs: tuple[Path, Path, Path]
    ) -> None:
        """CSV validation failure produces report with errors and no database."""
        csv_dir, schema_dir, output_path = project_dirs

        # Schema expects id,title,status but CSV has wrong headers
        (schema_dir / "nodes" / "requirement.csvschema").write_text(
            "# Requirement\n# id_field: id\n# csv_file: requirements.csv\n"
            "id,title,status\n"
        )
        (csv_dir / "requirements.csv").write_text(
            "id,wrong_col,status\nREQ-001,Bad,draft\n"
        )

        report = build_graph(csv_dir, schema_dir, output_path)

        assert report.success is False
        assert len(report.validation_errors) > 0
        assert not output_path.exists()

    @pytest.mark.traces("DC-003")
    def test_dangling_reference_prevents_build(
        self, project_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Dangling edge reference produces validation error and no database."""
        csv_dir, schema_dir, output_path = project_dirs

        (schema_dir / "nodes" / "requirement.csvschema").write_text(
            "# Requirement\n# id_field: id\n# csv_file: requirements.csv\n"
            "id,title,status\n"
        )
        (schema_dir / "nodes" / "design_contract.csvschema").write_text(
            "# DesignContract\n# id_field: id\n# csv_file: design_contracts.csv\n"
            "id,title,status\n"
        )
        (schema_dir / "edges" / "fulfilled_by.csvschema").write_text(
            "# FULFILLED_BY\n"
            "# references: requirement_id -> requirement, design_contract_id -> design_contract\n"
            "# csv_file: fulfilled_by.csv\n"
            "requirement_id,design_contract_id,completeness\n"
        )

        (csv_dir / "requirements.csv").write_text("id,title,status\nREQ-001,First,draft\n")
        (csv_dir / "design_contracts.csv").write_text("id,title,status\nDC-001,First,draft\n")
        (csv_dir / "fulfilled_by.csv").write_text(
            "requirement_id,design_contract_id,completeness\n"
            "REQ-001,DC-MISSING,full\n"
        )

        report = build_graph(csv_dir, schema_dir, output_path)

        assert report.success is False
        assert len(report.validation_errors) > 0
        assert not output_path.exists()

    @pytest.mark.traces("DC-003")
    def test_partial_data_gracefully_handled(
        self, project_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Schemas without matching CSVs are skipped, present data is built."""
        csv_dir, schema_dir, output_path = project_dirs

        # Two node schemas, but only one has a matching CSV
        (schema_dir / "nodes" / "requirement.csvschema").write_text(
            "# Requirement\n# id_field: id\n# csv_file: requirements.csv\n"
            "id,title,status\n"
        )
        (schema_dir / "nodes" / "test_case.csvschema").write_text(
            "# TestCase\n# id_field: id\n# csv_file: test_cases.csv\n"
            "id,title,status\n"
        )

        (csv_dir / "requirements.csv").write_text("id,title,status\nREQ-001,First,draft\n")
        # No test_cases.csv - should be skipped

        report = build_graph(csv_dir, schema_dir, output_path)

        assert report.success is True
        assert "Requirement" in report.tables_created
        assert report.tables_created["Requirement"] == 1
        assert "TestCase" in report.tables_skipped

    @pytest.mark.traces("DC-003")
    def test_no_partial_database_on_failure(
        self, project_dirs: tuple[Path, Path, Path]
    ) -> None:
        """On build failure, no partial database is left behind (atomic)."""
        csv_dir, schema_dir, output_path = project_dirs

        # Invalid data that fails validation
        (schema_dir / "nodes" / "requirement.csvschema").write_text(
            "# Requirement\n# id_field: id\n# csv_file: requirements.csv\n"
            "id,title,status\n"
        )
        (csv_dir / "requirements.csv").write_text(
            "id,title,status\nREQ-001,,draft\n"  # empty required field
        )

        report = build_graph(csv_dir, schema_dir, output_path)

        assert report.success is False
        assert not output_path.exists()

    @pytest.mark.traces("DC-003")
    def test_build_report_structure(
        self, populated_dirs: tuple[Path, Path, Path]
    ) -> None:
        """BuildReport contains expected fields with correct types."""
        csv_dir, schema_dir, output_path = populated_dirs

        report = build_graph(csv_dir, schema_dir, output_path)

        assert isinstance(report, BuildReport)
        assert isinstance(report.db_path, Path)
        assert isinstance(report.tables_created, dict)
        assert isinstance(report.tables_skipped, list)
        assert isinstance(report.validation_errors, list)
        assert isinstance(report.success, bool)

    @pytest.mark.traces("DC-003")
    def test_edge_properties_preserved(
        self, populated_dirs: tuple[Path, Path, Path]
    ) -> None:
        """Edge properties (non-FK columns) are preserved in the graph."""
        csv_dir, schema_dir, output_path = populated_dirs

        build_graph(csv_dir, schema_dir, output_path)

        db = kuzu.Database(str(output_path))
        conn = kuzu.Connection(db)
        rows = _query_to_dicts(
            conn,
            "MATCH (:Requirement)-[f:FULFILLED_BY]->(:DesignContract) "
            "RETURN f.completeness",
        )

        assert len(rows) == 1
        assert rows[0]["f.completeness"] == "full"


# --- Self-Application Tests (REQ-010) ---


class TestSelfApplicationBuildGraph:
    """Tests building the project's own traceability data into a graph.

    Proves REQ-010: framework can build its own data.
    """

    @pytest.mark.traces("DC-003")
    def test_project_graph_builds_successfully(self, tmp_path: Path) -> None:
        """Project's own traceability CSVs build into a valid Kuzu database."""
        project_root = Path(__file__).parent.parent

        csv_dir = project_root / "traceability"
        schema_dir = project_root / "schemas"
        output_path = tmp_path / "self_test_db"

        report = build_graph(csv_dir, schema_dir, output_path)

        assert report.success is True, f"Self-application build failed: {report.validation_errors}"
        assert output_path.exists()
        # We have requirements.csv, design_contracts.csv, fulfilled_by.csv
        assert "Requirement" in report.tables_created
        assert "DesignContract" in report.tables_created
        assert "FULFILLED_BY" in report.tables_created

    @pytest.mark.traces("DC-003")
    def test_project_graph_node_counts_match_csvs(self, tmp_path: Path) -> None:
        """Node counts in built graph match row counts in project CSVs."""
        project_root = Path(__file__).parent.parent

        csv_dir = project_root / "traceability"
        schema_dir = project_root / "schemas"
        output_path = tmp_path / "self_test_db"

        report = build_graph(csv_dir, schema_dir, output_path)

        assert report.success is True

        # Verify counts by querying the database
        db = kuzu.Database(str(output_path))
        conn = kuzu.Connection(db)

        for table_name, expected_count in report.tables_created.items():
            # Only check node tables (PascalCase, not UPPER_SNAKE)
            if table_name[0].isupper() and not table_name.isupper():
                rows = _query_to_dicts(conn, f"MATCH (n:{table_name}) RETURN count(n.id) AS cnt")
                actual = rows[0]["cnt"]
                assert actual == expected_count, (
                    f"{table_name}: expected {expected_count} rows, got {actual}"
                )

    @pytest.mark.traces("DC-003")
    def test_project_graph_edges_queryable(self, tmp_path: Path) -> None:
        """Project's FULFILLED_BY edges are queryable with correct structure."""
        project_root = Path(__file__).parent.parent

        csv_dir = project_root / "traceability"
        schema_dir = project_root / "schemas"
        output_path = tmp_path / "self_test_db"

        report = build_graph(csv_dir, schema_dir, output_path)
        assert report.success is True

        db = kuzu.Database(str(output_path))
        conn = kuzu.Connection(db)
        rows = _query_to_dicts(
            conn,
            "MATCH (r:Requirement)-[f:FULFILLED_BY]->(d:DesignContract) "
            "RETURN r.id, d.id, f.completeness ORDER BY r.id, d.id",
        )

        assert len(rows) > 0, "Expected at least one FULFILLED_BY edge"
        # All edges should have non-empty completeness
        for row in rows:
            assert row["f.completeness"] in ("full", "partial")
