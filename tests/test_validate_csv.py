"""Tests for CSV schema validator (DC-001) and reference integrity validator (DC-002).

Every test is linked to a design contract via @pytest.mark.traces.
Tests verify observable behavior (what the module accomplishes),
not implementation details.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_csv import (
    CsvSchema,
    SchemaError,
    parse_schema,
    validate_references,
    validate_schema,
)

# --- Fixtures ---


@pytest.fixture()
def tmp_schema(tmp_path: Path) -> Path:
    """Create a minimal node schema file."""
    schema = tmp_path / "test.csvschema"
    schema.write_text(
        "# Test node schema\n"
        "# id_field: id\n"
        "id,name,status\n"
        "# id: Unique identifier\n"
        "# name: Human-readable name\n"
        "# status: draft|approved\n"
    )
    return schema


@pytest.fixture()
def tmp_edge_schema(tmp_path: Path) -> Path:
    """Create a minimal edge schema file."""
    schema = tmp_path / "test_edge.csvschema"
    schema.write_text(
        "# Test edge schema\n# references: source_id -> source_node, target_id -> target_node\nsource_id,target_id,weight\n"
    )
    return schema


@pytest.fixture()
def valid_csv(tmp_path: Path) -> Path:
    """Create a valid CSV matching tmp_schema."""
    csv_file = tmp_path / "valid.csv"
    csv_file.write_text("id,name,status\nN-001,First,draft\nN-002,Second,approved\n")
    return csv_file


@pytest.fixture()
def valid_edge_csv(tmp_path: Path) -> Path:
    """Create a valid edge CSV."""
    csv_file = tmp_path / "valid_edge.csv"
    csv_file.write_text("source_id,target_id,weight\nS-001,T-001,high\n")
    return csv_file


# --- DC-001: Schema Validation Tests ---


class TestValidateSchema:
    """Tests for DC-001: CSV Schema Validator."""

    @pytest.mark.traces("DC-001")
    def test_valid_csv_passes(self, valid_csv: Path, tmp_schema: Path) -> None:
        """Valid CSV matching schema produces valid report with parsed rows."""
        report = validate_schema(valid_csv, tmp_schema)

        assert report.valid is True
        assert report.errors == []
        assert len(report.rows) == 2
        assert report.rows[0]["id"] == "N-001"
        assert report.rows[1]["name"] == "Second"

    @pytest.mark.traces("DC-001")
    def test_empty_required_field_detected(self, tmp_path: Path, tmp_schema: Path) -> None:
        """Empty required field produces error with row number and field name."""
        csv_file = tmp_path / "empty_field.csv"
        csv_file.write_text("id,name,status\nN-001,,draft\n")

        report = validate_schema(csv_file, tmp_schema)

        assert report.valid is False
        assert len(report.errors) == 1
        assert report.errors[0].row == 2
        assert report.errors[0].field_name == "name"
        assert "empty" in report.errors[0].message.lower()

    @pytest.mark.traces("DC-001")
    def test_duplicate_id_detected(self, tmp_path: Path, tmp_schema: Path) -> None:
        """Duplicate IDs within a CSV produce error identifying the duplicate."""
        csv_file = tmp_path / "dup_id.csv"
        csv_file.write_text("id,name,status\nN-001,First,draft\nN-001,Duplicate,approved\n")

        report = validate_schema(csv_file, tmp_schema)

        assert report.valid is False
        assert any("Duplicate ID" in e.message for e in report.errors)
        dup_error = [e for e in report.errors if "Duplicate" in e.message][0]
        assert dup_error.row == 3
        assert dup_error.field_name == "id"

    @pytest.mark.traces("DC-001")
    def test_header_mismatch_detected(self, tmp_path: Path, tmp_schema: Path) -> None:
        """CSV with wrong headers produces error listing expected vs actual."""
        csv_file = tmp_path / "bad_header.csv"
        csv_file.write_text("id,title,status\nN-001,First,draft\n")

        report = validate_schema(csv_file, tmp_schema)

        assert report.valid is False
        assert any("Header mismatch" in e.message for e in report.errors)

    @pytest.mark.traces("DC-001")
    def test_empty_csv_detected(self, tmp_path: Path, tmp_schema: Path) -> None:
        """Empty CSV file (no header, no rows) produces error."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")

        report = validate_schema(csv_file, tmp_schema)

        assert report.valid is False
        assert any("empty" in e.message.lower() for e in report.errors)

    @pytest.mark.traces("DC-001")
    def test_missing_file_raises(self, tmp_path: Path, tmp_schema: Path) -> None:
        """Missing CSV file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            validate_schema(tmp_path / "nonexistent.csv", tmp_schema)

    @pytest.mark.traces("DC-001")
    def test_bad_schema_raises(self, tmp_path: Path, valid_csv: Path) -> None:
        """Unparseable schema raises SchemaError."""
        bad_schema = tmp_path / "bad.csvschema"
        bad_schema.write_text("# Only comments, no header\n# Nothing here\n")

        with pytest.raises(SchemaError):
            validate_schema(valid_csv, bad_schema)

    @pytest.mark.traces("DC-001")
    def test_missing_schema_raises(self, tmp_path: Path, valid_csv: Path) -> None:
        """Missing schema file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            validate_schema(valid_csv, tmp_path / "nonexistent.csvschema")

    @pytest.mark.traces("DC-001")
    def test_all_errors_collected(self, tmp_path: Path, tmp_schema: Path) -> None:
        """Multiple errors in one CSV are ALL reported, not just the first."""
        csv_file = tmp_path / "multi_error.csv"
        csv_file.write_text("id,name,status\nN-001,,\nN-001,Second,\n")

        report = validate_schema(csv_file, tmp_schema)

        assert report.valid is False
        # Row 2: empty name, empty status
        # Row 3: duplicate ID, empty status
        assert len(report.errors) >= 3


# --- DC-002: Reference Integrity Tests ---


class TestValidateReferences:
    """Tests for DC-002: Reference Integrity Validator."""

    @pytest.mark.traces("DC-002")
    def test_valid_references_pass(self, tmp_path: Path, tmp_edge_schema: Path) -> None:
        """Edge CSV with all valid references produces valid report."""
        edge_csv = tmp_path / "good_edges.csv"
        edge_csv.write_text("source_id,target_id,weight\nS-001,T-001,high\n")

        source_schema = CsvSchema(headers=["id", "name"], id_field="id")
        target_schema = CsvSchema(headers=["id", "label"], id_field="id")

        report = validate_references(
            edge_csv,
            tmp_edge_schema,
            node_data={
                "source_node": [{"id": "S-001", "name": "Source"}],
                "target_node": [{"id": "T-001", "label": "Target"}],
            },
            node_schemas={
                "source_node": source_schema,
                "target_node": target_schema,
            },
        )

        assert report.valid is True
        assert report.errors == []

    @pytest.mark.traces("DC-002")
    def test_dangling_reference_detected(self, tmp_path: Path, tmp_edge_schema: Path) -> None:
        """Edge referencing non-existent node produces dangling reference error."""
        edge_csv = tmp_path / "dangling.csv"
        edge_csv.write_text("source_id,target_id,weight\nS-001,T-MISSING,high\n")

        source_schema = CsvSchema(headers=["id", "name"], id_field="id")
        target_schema = CsvSchema(headers=["id", "label"], id_field="id")

        report = validate_references(
            edge_csv,
            tmp_edge_schema,
            node_data={
                "source_node": [{"id": "S-001", "name": "Source"}],
                "target_node": [{"id": "T-001", "label": "Target"}],
            },
            node_schemas={
                "source_node": source_schema,
                "target_node": target_schema,
            },
        )

        assert report.valid is False
        assert any("Dangling reference" in e.message for e in report.errors)
        dangling = [e for e in report.errors if "Dangling" in e.message][0]
        assert dangling.field_name == "target_id"
        assert "T-MISSING" in dangling.message

    @pytest.mark.traces("DC-002")
    def test_both_endpoints_validated(self, tmp_path: Path, tmp_edge_schema: Path) -> None:
        """Both source and target endpoints are checked for validity."""
        edge_csv = tmp_path / "both_bad.csv"
        edge_csv.write_text("source_id,target_id,weight\nS-BAD,T-BAD,high\n")

        source_schema = CsvSchema(headers=["id", "name"], id_field="id")
        target_schema = CsvSchema(headers=["id", "label"], id_field="id")

        report = validate_references(
            edge_csv,
            tmp_edge_schema,
            node_data={
                "source_node": [{"id": "S-001", "name": "Source"}],
                "target_node": [{"id": "T-001", "label": "Target"}],
            },
            node_schemas={
                "source_node": source_schema,
                "target_node": target_schema,
            },
        )

        assert report.valid is False
        dangling_errors = [e for e in report.errors if "Dangling" in e.message]
        referenced_fields = {e.field_name for e in dangling_errors}
        assert "source_id" in referenced_fields
        assert "target_id" in referenced_fields

    @pytest.mark.traces("DC-002")
    def test_all_dangling_references_reported(self, tmp_path: Path, tmp_edge_schema: Path) -> None:
        """Multiple dangling references across rows are ALL reported."""
        edge_csv = tmp_path / "multi_dangling.csv"
        edge_csv.write_text("source_id,target_id,weight\nS-BAD1,T-001,high\nS-001,T-BAD2,low\n")

        source_schema = CsvSchema(headers=["id", "name"], id_field="id")
        target_schema = CsvSchema(headers=["id", "label"], id_field="id")

        report = validate_references(
            edge_csv,
            tmp_edge_schema,
            node_data={
                "source_node": [{"id": "S-001", "name": "Source"}],
                "target_node": [{"id": "T-001", "label": "Target"}],
            },
            node_schemas={
                "source_node": source_schema,
                "target_node": target_schema,
            },
        )

        assert report.valid is False
        dangling_errors = [e for e in report.errors if "Dangling" in e.message]
        assert len(dangling_errors) == 2

    @pytest.mark.traces("DC-002")
    def test_missing_node_data_detected(self, tmp_path: Path, tmp_edge_schema: Path) -> None:
        """Edge referencing a node type with no provided data produces error."""
        edge_csv = tmp_path / "no_node_data.csv"
        edge_csv.write_text("source_id,target_id,weight\nS-001,T-001,high\n")

        source_schema = CsvSchema(headers=["id", "name"], id_field="id")

        report = validate_references(
            edge_csv,
            tmp_edge_schema,
            node_data={
                "source_node": [{"id": "S-001", "name": "Source"}],
                # target_node intentionally missing
            },
            node_schemas={
                "source_node": source_schema,
            },
        )

        assert report.valid is False
        assert any("No node data" in e.message for e in report.errors)


# --- Schema Parser Tests ---


class TestParseSchema:
    """Tests for schema parsing (supports DC-001 and DC-002)."""

    @pytest.mark.traces("DC-001")
    def test_parse_node_schema(self, tmp_schema: Path) -> None:
        """Node schema parsed with headers and id_field."""
        schema = parse_schema(tmp_schema)

        assert schema.headers == ["id", "name", "status"]
        assert schema.id_field == "id"
        assert schema.references == {}

    @pytest.mark.traces("DC-002")
    def test_parse_edge_schema(self, tmp_edge_schema: Path) -> None:
        """Edge schema parsed with headers and references."""
        schema = parse_schema(tmp_edge_schema)

        assert schema.headers == ["source_id", "target_id", "weight"]
        assert schema.id_field is None
        assert schema.references == {
            "source_id": "source_node",
            "target_id": "target_node",
        }

    @pytest.mark.traces("DC-001")
    def test_parse_missing_schema_raises(self, tmp_path: Path) -> None:
        """Missing schema file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_schema(tmp_path / "nonexistent.csvschema")

    @pytest.mark.traces("DC-001")
    def test_parse_empty_schema_raises(self, tmp_path: Path) -> None:
        """Schema with no header row raises SchemaError."""
        schema = tmp_path / "empty.csvschema"
        schema.write_text("# Only comments\n")

        with pytest.raises(SchemaError):
            parse_schema(schema)


# --- Self-Application Tests (REQ-010) ---


class TestSelfApplication:
    """Tests validating project's own traceability CSVs.

    Proves REQ-010: framework can validate its own data.
    Uses REAL schemas and CSVs from the project.
    """

    @pytest.mark.traces("DC-001")
    @pytest.mark.traces("DC-002")
    def test_project_requirements_csv_valid(self) -> None:
        """Project's requirements.csv validates against requirement.csvschema."""
        project_root = Path(__file__).parent.parent

        requirements_csv = project_root / "traceability" / "requirements.csv"
        requirements_schema = project_root / "schemas" / "nodes" / "requirement.csvschema"

        assert requirements_csv.exists(), "requirements.csv not found"
        assert requirements_schema.exists(), "requirement.csvschema not found"

        report = validate_schema(requirements_csv, requirements_schema)

        assert report.valid is True, f"requirements.csv validation failed: {report.errors}"
        assert len(report.rows) > 0, "requirements.csv should have data rows"

    @pytest.mark.traces("DC-001")
    @pytest.mark.traces("DC-002")
    def test_project_design_contracts_csv_valid(self) -> None:
        """Project's design_contracts.csv validates against design_contract.csvschema."""
        project_root = Path(__file__).parent.parent

        contracts_csv = project_root / "traceability" / "design_contracts.csv"
        contracts_schema = project_root / "schemas" / "nodes" / "design_contract.csvschema"

        assert contracts_csv.exists(), "design_contracts.csv not found"
        assert contracts_schema.exists(), "design_contract.csvschema not found"

        report = validate_schema(contracts_csv, contracts_schema)

        assert report.valid is True, f"design_contracts.csv validation failed: {report.errors}"
        assert len(report.rows) > 0, "design_contracts.csv should have data rows"

    @pytest.mark.traces("DC-002")
    def test_project_fulfilled_by_references_valid(self) -> None:
        """Project's fulfilled_by.csv has valid references to requirements and design_contracts.

        This is the critical integration test: validates reference integrity
        across the actual project traceability data.
        """
        project_root = Path(__file__).parent.parent

        # Load node CSVs and schemas
        requirements_csv = project_root / "traceability" / "requirements.csv"
        requirements_schema_path = project_root / "schemas" / "nodes" / "requirement.csvschema"
        contracts_csv = project_root / "traceability" / "design_contracts.csv"
        contracts_schema_path = project_root / "schemas" / "nodes" / "design_contract.csvschema"

        # Load edge CSV and schema
        fulfilled_by_csv = project_root / "traceability" / "fulfilled_by.csv"
        fulfilled_by_schema = project_root / "schemas" / "edges" / "fulfilled_by.csvschema"

        # Validate node CSVs first
        requirements_report = validate_schema(requirements_csv, requirements_schema_path)
        contracts_report = validate_schema(contracts_csv, contracts_schema_path)

        assert requirements_report.valid is True, f"requirements.csv invalid: {requirements_report.errors}"
        assert contracts_report.valid is True, f"design_contracts.csv invalid: {contracts_report.errors}"

        # Parse schemas
        requirements_schema = parse_schema(requirements_schema_path)
        contracts_schema = parse_schema(contracts_schema_path)

        # Validate reference integrity
        report = validate_references(
            fulfilled_by_csv,
            fulfilled_by_schema,
            node_data={
                "requirement": requirements_report.rows,
                "design_contract": contracts_report.rows,
            },
            node_schemas={
                "requirement": requirements_schema,
                "design_contract": contracts_schema,
            },
        )

        assert report.valid is True, f"fulfilled_by.csv reference integrity failed: {report.errors}"
        assert len(report.rows) > 0, "fulfilled_by.csv should have edge data"
