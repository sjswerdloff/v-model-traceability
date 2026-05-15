"""Tests for CSV migration tool (migrate_csv).

Tests verify observable behavior (contracts), not implementation details.
Every test uses tmp_path to isolate test data from production files.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.migrate_csv import (
    MigrationError,
    apply_migration,
    plan_migration,
)
from scripts.validate_csv import validate_schema

# --- Fixtures ---


@pytest.fixture()
def schema_with_optional(tmp_path: Path) -> Path:
    """Schema with two optional columns, used for migration tests."""
    schema = tmp_path / "item.csvschema"
    schema.write_text("# Item node schema\n# id_field: id\n# optional: notes, approved_by\nid,name,status,notes,approved_by\n")
    return schema


@pytest.fixture()
def schema_all_required(tmp_path: Path) -> Path:
    """Schema with all required columns, no optionals."""
    schema = tmp_path / "strict.csvschema"
    schema.write_text("# Strict schema - all required\n# id_field: id\nid,name,status\n")
    return schema


@pytest.fixture()
def csv_missing_optional_columns(tmp_path: Path) -> Path:
    """CSV that is missing the optional 'notes' and 'approved_by' columns."""
    csv_file = tmp_path / "items.csv"
    csv_file.write_text("id,name,status\nI-001,Alpha,draft\nI-002,Beta,approved\n")
    return csv_file


@pytest.fixture()
def csv_full_match(tmp_path: Path) -> Path:
    """CSV that already matches the schema_with_optional exactly."""
    csv_file = tmp_path / "items_full.csv"
    csv_file.write_text("id,name,status,notes,approved_by\nI-001,Alpha,draft,,\n")
    return csv_file


# --- plan_migration: single optional column missing ---


class TestPlanMigrationSingleMissing:
    """Contract: plan_migration detects one missing optional column."""

    def test_missing_column_appears_in_columns_to_add(self, tmp_path: Path, schema_with_optional: Path) -> None:
        """Missing optional column is listed in plan.columns_to_add."""
        csv_file = tmp_path / "partial.csv"
        csv_file.write_text("id,name,status,approved_by\nI-001,Alpha,draft,\n")

        plan = plan_migration(csv_file, schema_with_optional)

        assert "notes" in plan.columns_to_add
        assert plan.errors == []

    def test_plan_row_count_matches_csv(self, tmp_path: Path, schema_with_optional: Path) -> None:
        """MigrationPlan.row_count reflects the number of data rows in the CSV."""
        csv_file = tmp_path / "rows.csv"
        csv_file.write_text("id,name,status,approved_by\nI-001,A,draft,\nI-002,B,approved,\n")

        plan = plan_migration(csv_file, schema_with_optional)

        assert plan.row_count == 2

    def test_plan_paths_are_preserved(self, tmp_path: Path, schema_with_optional: Path) -> None:
        """MigrationPlan stores csv_path and schema_path exactly as supplied."""
        csv_file = tmp_path / "partial.csv"
        csv_file.write_text("id,name,status,approved_by\nI-001,Alpha,draft,\n")

        plan = plan_migration(csv_file, schema_with_optional)

        assert plan.csv_path == csv_file
        assert plan.schema_path == schema_with_optional


# --- plan_migration: multiple optional columns missing ---


class TestPlanMigrationMultipleMissing:
    """Contract: plan_migration detects all missing optional columns."""

    def test_all_missing_optional_columns_reported(
        self, csv_missing_optional_columns: Path, schema_with_optional: Path
    ) -> None:
        """All missing optional columns appear in columns_to_add."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)

        assert "notes" in plan.columns_to_add
        assert "approved_by" in plan.columns_to_add
        assert plan.errors == []

    def test_existing_columns_not_in_columns_to_add(
        self, csv_missing_optional_columns: Path, schema_with_optional: Path
    ) -> None:
        """Columns already present in the CSV are not listed as needing addition."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)

        assert "id" not in plan.columns_to_add
        assert "name" not in plan.columns_to_add
        assert "status" not in plan.columns_to_add

    def test_target_headers_contains_all_schema_columns(
        self, csv_missing_optional_columns: Path, schema_with_optional: Path
    ) -> None:
        """plan.target_headers matches the schema header order exactly."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)

        assert plan.target_headers == ["id", "name", "status", "notes", "approved_by"]

    def test_current_headers_reflects_csv(self, csv_missing_optional_columns: Path, schema_with_optional: Path) -> None:
        """plan.current_headers reflects what is actually in the CSV."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)

        assert plan.current_headers == ["id", "name", "status"]


# --- plan_migration: required column missing → error ---


class TestPlanMigrationRequiredMissing:
    """Contract: missing required columns are reported as errors, not added."""

    def test_missing_required_column_in_errors(self, tmp_path: Path, schema_all_required: Path) -> None:
        """CSV missing a required column produces an error entry in plan.errors."""
        csv_file = tmp_path / "no_status.csv"
        csv_file.write_text("id,name\nI-001,Alpha\n")

        plan = plan_migration(csv_file, schema_all_required)

        assert any("status" in err for err in plan.errors)

    def test_missing_required_column_not_in_columns_to_add(self, tmp_path: Path, schema_all_required: Path) -> None:
        """Required columns that are missing must NOT appear in columns_to_add."""
        csv_file = tmp_path / "no_status.csv"
        csv_file.write_text("id,name\nI-001,Alpha\n")

        plan = plan_migration(csv_file, schema_all_required)

        assert "status" not in plan.columns_to_add

    def test_plan_errors_is_empty_when_only_optional_missing(
        self, csv_missing_optional_columns: Path, schema_with_optional: Path
    ) -> None:
        """No errors when only optional columns are missing."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)

        assert plan.errors == []


# --- plan_migration: already matches schema ---


class TestPlanMigrationNoOp:
    """Contract: plan_migration is a no-op when CSV already matches schema."""

    def test_no_columns_to_add_when_csv_matches_schema(self, csv_full_match: Path, schema_with_optional: Path) -> None:
        """Plan has no columns_to_add when CSV already matches schema."""
        plan = plan_migration(csv_full_match, schema_with_optional)

        assert plan.columns_to_add == []
        assert plan.errors == []


# --- plan_migration: extra columns in CSV ---


class TestPlanMigrationExtraColumns:
    """Contract: extra columns in CSV that are not in schema are reported as warnings."""

    def test_extra_columns_reported_as_warnings(self, tmp_path: Path, schema_all_required: Path) -> None:
        """Columns in CSV but not in schema appear in plan.warnings."""
        csv_file = tmp_path / "extra.csv"
        csv_file.write_text("id,name,status,legacy_field\nI-001,A,draft,old\n")

        plan = plan_migration(csv_file, schema_all_required)

        assert hasattr(plan, "warnings")
        assert any("legacy_field" in w for w in plan.warnings)

    def test_extra_columns_not_added_to_errors(self, tmp_path: Path, schema_all_required: Path) -> None:
        """Extra columns are warnings only — they don't produce errors."""
        csv_file = tmp_path / "extra.csv"
        csv_file.write_text("id,name,status,legacy_field\nI-001,A,draft,old\n")

        plan = plan_migration(csv_file, schema_all_required)

        assert plan.errors == []


# --- apply_migration: data preservation ---


class TestApplyMigrationDataPreservation:
    """Contract: apply_migration preserves all existing data exactly."""

    def test_existing_row_data_unchanged_after_migration(
        self, csv_missing_optional_columns: Path, schema_with_optional: Path, tmp_path: Path
    ) -> None:
        """All existing column values are preserved exactly after migration."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)
        apply_migration(csv_missing_optional_columns, plan)

        with csv_missing_optional_columns.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["id"] == "I-001"
        assert rows[0]["name"] == "Alpha"
        assert rows[0]["status"] == "draft"
        assert rows[1]["id"] == "I-002"
        assert rows[1]["name"] == "Beta"
        assert rows[1]["status"] == "approved"

    def test_new_columns_have_empty_values(self, csv_missing_optional_columns: Path, schema_with_optional: Path) -> None:
        """Newly added columns have empty string values for all existing rows."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)
        apply_migration(csv_missing_optional_columns, plan)

        with csv_missing_optional_columns.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["notes"] == ""
        assert rows[0]["approved_by"] == ""
        assert rows[1]["notes"] == ""
        assert rows[1]["approved_by"] == ""


# --- apply_migration: column insertion order ---


class TestApplyMigrationColumnOrder:
    """Contract: new columns are inserted at the position they appear in the schema."""

    def test_columns_inserted_in_schema_order_not_appended(self, tmp_path: Path, schema_with_optional: Path) -> None:
        """New columns appear in schema header order, not appended at end.

        Schema order: id, name, status, notes, approved_by
        CSV has:      id, name, approved_by
        After migration: id, name, status (required, already there), notes (inserted), approved_by
        BUT status is required so this scenario would error — use a different scenario.

        Schema: id, name, status, notes, approved_by
        CSV has: id, name, status, approved_by  (notes is missing, inserted before approved_by)
        After migration header order must be: id, name, status, notes, approved_by
        """
        csv_file = tmp_path / "partial_order.csv"
        # approved_by is present, notes is missing — notes should be inserted before approved_by
        csv_file.write_text("id,name,status,approved_by\nI-001,Alpha,draft,Cora\n")

        plan = plan_migration(csv_file, schema_with_optional)
        apply_migration(csv_file, plan)

        with csv_file.open(newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or [])

        # notes must come before approved_by in output header
        assert fieldnames.index("notes") < fieldnames.index("approved_by")
        # complete order must match schema
        assert fieldnames == ["id", "name", "status", "notes", "approved_by"]

    def test_row_count_unchanged_after_migration(self, csv_missing_optional_columns: Path, schema_with_optional: Path) -> None:
        """Row count is unchanged after migration — no rows dropped or duplicated."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)
        apply_migration(csv_missing_optional_columns, plan)

        with csv_missing_optional_columns.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 2


# --- apply_migration: post-migration validation ---


class TestApplyMigrationValidation:
    """Contract: migrated CSV passes validate_schema."""

    def test_migrated_csv_passes_validate_schema(self, csv_missing_optional_columns: Path, schema_with_optional: Path) -> None:
        """After migration, the CSV passes schema validation."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)
        apply_migration(csv_missing_optional_columns, plan)

        report = validate_schema(csv_missing_optional_columns, schema_with_optional)

        assert report.valid is True, f"Post-migration validation failed: {report.errors}"

    def test_migrated_csv_has_correct_header(self, csv_missing_optional_columns: Path, schema_with_optional: Path) -> None:
        """After migration, CSV header matches schema exactly."""
        plan = plan_migration(csv_missing_optional_columns, schema_with_optional)
        apply_migration(csv_missing_optional_columns, plan)

        with csv_missing_optional_columns.open(newline="") as f:
            reader = csv.DictReader(f)
            actual_headers = list(reader.fieldnames or [])

        assert actual_headers == ["id", "name", "status", "notes", "approved_by"]


# --- apply_migration: error guard ---


class TestApplyMigrationErrorGuard:
    """Contract: apply_migration raises MigrationError when plan has errors."""

    def test_apply_raises_when_plan_has_errors(self, tmp_path: Path, schema_all_required: Path) -> None:
        """apply_migration raises MigrationError if plan.errors is non-empty."""
        csv_file = tmp_path / "no_status.csv"
        csv_file.write_text("id,name\nI-001,Alpha\n")

        plan = plan_migration(csv_file, schema_all_required)
        assert plan.errors  # precondition: plan must have errors

        with pytest.raises(MigrationError):
            apply_migration(csv_file, plan)

    def test_apply_does_not_modify_csv_when_plan_has_errors(self, tmp_path: Path, schema_all_required: Path) -> None:
        """CSV content is not modified when apply_migration raises MigrationError."""
        csv_file = tmp_path / "no_status.csv"
        original_content = "id,name\nI-001,Alpha\n"
        csv_file.write_text(original_content)

        plan = plan_migration(csv_file, schema_all_required)

        try:
            apply_migration(csv_file, plan)
        except MigrationError:
            pass

        assert csv_file.read_text() == original_content


# --- apply_migration: no-op when nothing to add ---


class TestApplyMigrationNoop:
    """Contract: apply_migration with no columns to add preserves the file exactly."""

    def test_noop_migration_preserves_file_content(self, csv_full_match: Path, schema_with_optional: Path) -> None:
        """When no columns need adding, file content is identical after apply."""
        original_content = csv_full_match.read_text()
        plan = plan_migration(csv_full_match, schema_with_optional)
        apply_migration(csv_full_match, plan)

        assert csv_full_match.read_text() == original_content


# --- plan_migration: file error handling ---


class TestPlanMigrationFileErrors:
    """Contract: plan_migration raises on missing files."""

    def test_missing_csv_raises_file_not_found(self, tmp_path: Path, schema_with_optional: Path) -> None:
        """Missing CSV file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            plan_migration(tmp_path / "nonexistent.csv", schema_with_optional)

    def test_missing_schema_raises_file_not_found(self, tmp_path: Path, csv_missing_optional_columns: Path) -> None:
        """Missing schema file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            plan_migration(csv_missing_optional_columns, tmp_path / "nonexistent.csvschema")
