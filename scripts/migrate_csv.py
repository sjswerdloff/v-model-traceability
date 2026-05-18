"""CSV migration tool for the V-model traceability framework.

Upgrades CSV files to match their current schema by adding missing optional
columns.  Required columns that are absent are reported as errors — they
cannot be auto-migrated because the tool has no way to supply meaningful
values.

Usage (library):
    from scripts.migrate_csv import plan_migration, apply_migration

Usage (CLI):
    python -m scripts.migrate_csv --schema schemas/nodes/item.csvschema \\
        --csv traceability/items.csv [--apply]
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.validate_csv import parse_schema


class MigrationError(Exception):
    """Raised when a migration cannot be applied due to plan errors."""


@dataclass
class MigrationPlan:
    """Describes what changes are needed to bring a CSV up to its schema.

    Attributes:
        csv_path: Path to the CSV file to be migrated.
        schema_path: Path to the .csvschema file used for planning.
        columns_to_add: Optional schema columns absent from the CSV.
        errors: Required schema columns absent from the CSV (cannot auto-add).
        warnings: CSV columns not present in the schema (extra / legacy columns).
        current_headers: Header row as read from the CSV.
        target_headers: Full header row from the schema (desired final state).
        row_count: Number of data rows (excluding the header) in the CSV.
    """

    csv_path: Path
    schema_path: Path
    columns_to_add: list[str]
    errors: list[str]
    warnings: list[str]
    current_headers: list[str]
    target_headers: list[str]
    row_count: int = 0


def plan_migration(csv_path: Path, schema_path: Path) -> MigrationPlan:
    """Analyse a CSV against its schema and produce a migration plan.

    Compares the CSV's current headers against the schema's header row.
    Columns that appear in the schema but not the CSV are classified as:
    - addable (optional columns) → appear in ``columns_to_add``
    - errors (required columns) → appear in ``errors``

    Columns in the CSV that are not in the schema are reported as warnings
    but are otherwise left untouched.

    Args:
        csv_path: Path to the CSV file to be migrated.
        schema_path: Path to the .csvschema file to migrate toward.

    Returns:
        MigrationPlan describing the changes needed (possibly empty).

    Raises:
        FileNotFoundError: If csv_path or schema_path does not exist.
        SchemaError: If the schema file cannot be parsed.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    schema = parse_schema(schema_path)  # raises FileNotFoundError / SchemaError

    # Read current CSV headers and count rows.
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        current_headers: list[str] = [h.strip() for h in (reader.fieldnames or [])]
        row_count = sum(1 for _ in reader)

    current_set = set(current_headers)
    schema_set = set(schema.headers)

    # Columns present in schema but absent from CSV.
    missing_columns = [col for col in schema.headers if col not in current_set]

    columns_to_add: list[str] = []
    errors: list[str] = []

    for col in missing_columns:
        if col in schema.optional_fields:
            columns_to_add.append(col)
        else:
            errors.append(f"Required column '{col}' is missing from CSV and cannot be auto-migrated")

    # Columns present in CSV but not in schema → warnings only.
    extra_columns = [col for col in current_headers if col not in schema_set]
    warnings: list[str] = [
        f"Column '{col}' is present in CSV but not in schema (extra / legacy column)" for col in extra_columns
    ]

    return MigrationPlan(
        csv_path=csv_path,
        schema_path=schema_path,
        columns_to_add=columns_to_add,
        errors=errors,
        warnings=warnings,
        current_headers=current_headers,
        target_headers=list(schema.headers),
        row_count=row_count,
    )


def apply_migration(csv_path: Path, plan: MigrationPlan) -> None:
    """Write new columns into the CSV as described by a MigrationPlan.

    New columns are inserted at the positions they occupy in the schema header,
    not appended at the end.  Existing column values are preserved exactly.
    Columns that are in the CSV but not the schema are kept in place (they are
    not removed).

    If ``plan.columns_to_add`` is empty, the function returns immediately
    without modifying the file.

    Args:
        csv_path: Path to the CSV file to modify in place.
        plan: The MigrationPlan produced by :func:`plan_migration`.

    Raises:
        MigrationError: If ``plan.errors`` is non-empty.  The CSV is not
            modified in this case.
    """
    if plan.errors:
        raise MigrationError(f"Cannot apply migration: {len(plan.errors)} error(s) — " + "; ".join(plan.errors))

    if not plan.columns_to_add:
        # Nothing to do.
        return

    # Determine the output column order:
    # Start with the schema's header order, then append any CSV-only extra
    # columns (legacy columns) at the end, preserving their relative order.
    schema_column_set = set(plan.target_headers)
    extra_columns = [col for col in plan.current_headers if col not in schema_column_set]
    output_headers = plan.target_headers + extra_columns

    # Read existing rows into memory (files are typically small in this tooling).
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, str]] = list(reader)

    # Write back with the new column order, filling new columns with empty strings.
    with csv_path.open(mode="w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Ensure every new column exists with at least an empty value.
            for col in plan.columns_to_add:
                row.setdefault(col, "")
            writer.writerow(row)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Migrate a CSV file to match its current schema by adding missing optional columns."
    )
    parser.add_argument("--schema", required=True, type=Path, help="Path to .csvschema file")
    parser.add_argument("--csv", required=True, type=Path, help="Path to CSV file")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually write changes.  Without this flag, the tool runs in dry-run mode.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to sys.argv[1:] when None).

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    csv_path: Path = args.csv
    schema_path: Path = args.schema

    try:
        plan = plan_migration(csv_path, schema_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if plan.errors:
        print("Migration blocked — required columns are missing:", file=sys.stderr)
        for err in plan.errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    if plan.warnings:
        for warning in plan.warnings:
            print(f"WARNING: {warning}")

    if not plan.columns_to_add:
        print(f"{csv_path}: already matches schema — no migration needed.")
        return 0

    if not args.apply:
        # Dry-run output.
        print(f"Dry run — {csv_path} requires migration:")
        print(f"  Columns to add : {plan.columns_to_add}")
        print(f"  Current header : {plan.current_headers}")
        print(f"  Target header  : {plan.target_headers}")
        print(f"  Rows affected  : {plan.row_count}")
        print("Re-run with --apply to write changes.")
        return 0

    try:
        apply_migration(csv_path, plan)
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"Migrated {csv_path}: added {len(plan.columns_to_add)} column(s) "
        f"({', '.join(plan.columns_to_add)}) across {plan.row_count} row(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
