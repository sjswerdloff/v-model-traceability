"""CSV Schema Validator for V-model traceability framework.

Provides two validation passes:
- DC-001: Schema validation (well-formed CSV matching schema)
- DC-002: Reference integrity validation (FK resolution)

Usage:
    from scripts.validate_csv import validate_schema, validate_references
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


class SchemaError(Exception):
    """Raised when a .csvschema file cannot be parsed."""


@dataclass
class ValidationError:
    """A single validation error."""

    row: int | None  # None for file-level errors
    field_name: str | None
    message: str


@dataclass
class CsvValidationReport:
    """Result of CSV validation."""

    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)


@dataclass
class CsvSchema:
    """Parsed csvschema definition."""

    headers: list[str]
    id_field: str | None = None
    references: dict[str, str] = field(default_factory=dict)
    csv_file: str | None = None
    optional_fields: set[str] = field(default_factory=set)


def parse_schema(schema_path: Path) -> CsvSchema:
    """Parse a .csvschema file into a CsvSchema object.

    Args:
        schema_path: Path to the .csvschema file.

    Returns:
        Parsed CsvSchema with headers, id_field, and references.

    Raises:
        SchemaError: If the schema file cannot be parsed.
        FileNotFoundError: If the schema file doesn't exist.
    """
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    headers: list[str] = []
    id_field: str | None = None
    references: dict[str, str] = {}
    csv_file: str | None = None
    optional_fields: set[str] = set()

    try:
        text = schema_path.read_text()
    except Exception as e:
        raise SchemaError(f"Cannot read schema {schema_path}: {e}") from e

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("# id_field:"):
            id_field = line.split(":", 1)[1].strip()
        elif line.startswith("# csv_file:"):
            csv_file = line.split(":", 1)[1].strip()
        elif line.startswith("# references:"):
            ref_str = line.split(":", 1)[1].strip()
            for pair in ref_str.split(","):
                pair = pair.strip()
                if "->" in pair:
                    col, node_type = pair.split("->", 1)
                    references[col.strip()] = node_type.strip()
        elif line.startswith("# optional:"):
            # Optional field declaration: fields may be empty without failing validation.
            # Example: ``# optional: approved_by, approval_date``
            opt_str = line.split(":", 1)[1].strip()
            for name in opt_str.split(","):
                name = name.strip()
                if name:
                    optional_fields.add(name)
        elif not line.startswith("#"):
            # First non-comment, non-annotation line is the header
            if not headers:
                headers = [h.strip() for h in line.split(",")]

    if not headers:
        raise SchemaError(f"No header row found in schema {schema_path}")

    # A field declared optional must actually appear in the header.
    unknown_optional = optional_fields - set(headers)
    if unknown_optional:
        raise SchemaError(
            f"Schema {schema_path} declares optional field(s) {sorted(unknown_optional)} "
            f"that are not present in the header {headers}"
        )

    return CsvSchema(
        headers=headers,
        id_field=id_field,
        references=references,
        csv_file=csv_file,
        optional_fields=optional_fields,
    )


def validate_schema(csv_path: Path, schema_path: Path) -> CsvValidationReport:
    """DC-001: Validate CSV structure against schema.

    Checks:
    - CSV structure matches schema header exactly
    - All required fields are present and non-empty in every row
    - No duplicate IDs (if id_field defined in schema)
    - All errors collected before returning (not fail-fast)

    Args:
        csv_path: Path to the CSV data file.
        schema_path: Path to the corresponding .csvschema file.

    Returns:
        CsvValidationReport with valid flag, errors list, and parsed rows.

    Raises:
        FileNotFoundError: If csv_path doesn't exist.
        SchemaError: If schema_path cannot be parsed.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    schema = parse_schema(schema_path)
    errors: list[ValidationError] = []
    rows: list[dict[str, str]] = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            errors.append(ValidationError(row=None, field_name=None, message="CSV file is empty"))
            return CsvValidationReport(valid=False, errors=errors, rows=rows)

        actual_headers = [h.strip() for h in reader.fieldnames]
        if actual_headers != schema.headers:
            errors.append(
                ValidationError(
                    row=None,
                    field_name=None,
                    message=f"Header mismatch: expected {schema.headers}, got {actual_headers}",
                )
            )

        seen_ids: set[str] = set()

        for row_num, row in enumerate(reader, start=2):  # row 1 is header
            rows.append(row)

            # Check required fields non-empty. Fields listed in the schema's
            # ``# optional:`` annotation may be empty without failing validation.
            for field_name in schema.headers:
                if field_name in schema.optional_fields:
                    continue
                value = row.get(field_name, "").strip()
                if not value:
                    errors.append(
                        ValidationError(
                            row=row_num,
                            field_name=field_name,
                            message=f"Required field '{field_name}' is empty",
                        )
                    )

            # Check duplicate IDs
            if schema.id_field:
                id_value = row.get(schema.id_field, "").strip()
                if id_value:
                    if id_value in seen_ids:
                        errors.append(
                            ValidationError(
                                row=row_num,
                                field_name=schema.id_field,
                                message=f"Duplicate ID: '{id_value}'",
                            )
                        )
                    else:
                        seen_ids.add(id_value)

    return CsvValidationReport(valid=len(errors) == 0, errors=errors, rows=rows)


def validate_references(
    edge_csv_path: Path,
    edge_schema_path: Path,
    node_data: dict[str, list[dict[str, str]]],
    node_schemas: dict[str, CsvSchema],
) -> CsvValidationReport:
    """DC-002: Validate reference integrity for edge CSVs.

    Checks that every foreign key in an edge CSV references an existing node ID.
    Both endpoints of every edge are validated.
    Reports ALL dangling references, not just the first.

    Args:
        edge_csv_path: Path to the edge CSV file.
        edge_schema_path: Path to the edge .csvschema file.
        node_data: Dict mapping node type name to validated row lists.
        node_schemas: Dict mapping node type name to parsed CsvSchema.

    Returns:
        CsvValidationReport with combined schema + reference errors.

    Raises:
        FileNotFoundError: If edge_csv_path doesn't exist.
        SchemaError: If edge_schema_path cannot be parsed.
    """
    edge_schema = parse_schema(edge_schema_path)

    if not edge_schema.references:
        # No references to validate - just do schema validation
        return validate_schema(edge_csv_path, edge_schema_path)

    # First pass: schema validation
    report = validate_schema(edge_csv_path, edge_schema_path)

    # Build ID sets for each referenced node type
    id_sets: dict[str, set[str]] = {}
    for node_type, rows in node_data.items():
        node_schema = node_schemas.get(node_type)
        if node_schema and node_schema.id_field:
            id_sets[node_type] = {row.get(node_schema.id_field, "").strip() for row in rows}

    # Second pass: reference integrity
    ref_errors: list[ValidationError] = []
    for row_num, row in enumerate(report.rows, start=2):
        for col, target_node_type in edge_schema.references.items():
            fk_value = row.get(col, "").strip()
            if not fk_value:
                continue  # Empty FK already caught by schema validation

            target_ids = id_sets.get(target_node_type)
            if target_ids is None:
                ref_errors.append(
                    ValidationError(
                        row=row_num,
                        field_name=col,
                        message=f"No node data provided for referenced type '{target_node_type}'",
                    )
                )
            elif fk_value not in target_ids:
                ref_errors.append(
                    ValidationError(
                        row=row_num,
                        field_name=col,
                        message=f"Dangling reference: '{fk_value}' not found in {target_node_type}",
                    )
                )

    all_errors = report.errors + ref_errors
    return CsvValidationReport(valid=len(all_errors) == 0, errors=all_errors, rows=report.rows)


def validate_node_references(
    node_csv_path: Path,
    node_schema_path: Path,
    node_data: dict[str, list[dict[str, str]]],
    node_schemas: dict[str, CsvSchema],
) -> CsvValidationReport:
    """DC-002b: Validate FK reference integrity for node CSVs.

    Node schemas may declare ``# references:`` directives that point FK columns
    at other node types.  This function validates those intra-node references so
    they do not silently escape the validation pipeline.

    Checks:
    - For each FK column in ``references``, every non-empty value must resolve
      to a row ID in the target node type.
    - Empty FK values are allowed (optional FK columns are not penalised).
    - All dangling references are collected before returning (not fail-fast).

    Args:
        node_csv_path: Path to the node CSV data file.
        node_schema_path: Path to the node .csvschema file.
        node_data: Dict mapping node type name to validated row lists.
        node_schemas: Dict mapping node type name to parsed CsvSchema.

    Returns:
        CsvValidationReport with combined schema + reference errors and parsed rows.

    Raises:
        FileNotFoundError: If node_csv_path doesn't exist.
        SchemaError: If node_schema_path cannot be parsed.
    """
    node_schema = parse_schema(node_schema_path)

    if not node_schema.references:
        # No FK columns to validate — schema validation only.
        return validate_schema(node_csv_path, node_schema_path)

    # First pass: schema validation (header check, required fields, duplicate IDs).
    report = validate_schema(node_csv_path, node_schema_path)

    # Build ID sets for each referenced node type.
    id_sets: dict[str, set[str]] = {}
    for node_type, rows in node_data.items():
        ref_schema = node_schemas.get(node_type)
        if ref_schema and ref_schema.id_field:
            id_sets[node_type] = {row.get(ref_schema.id_field, "").strip() for row in rows}

    # Second pass: reference integrity for FK columns.
    ref_errors: list[ValidationError] = []
    for row_num, row in enumerate(report.rows, start=2):
        for col, target_node_type in node_schema.references.items():
            fk_value = row.get(col, "").strip()
            if not fk_value:
                # Empty FK is allowed for optional FK columns.
                continue

            target_ids = id_sets.get(target_node_type)
            if target_ids is None:
                ref_errors.append(
                    ValidationError(
                        row=row_num,
                        field_name=col,
                        message=f"No node data provided for referenced type '{target_node_type}'",
                    )
                )
            elif fk_value not in target_ids:
                ref_errors.append(
                    ValidationError(
                        row=row_num,
                        field_name=col,
                        message=f"Dangling reference: '{fk_value}' not found in {target_node_type}",
                    )
                )

    all_errors = report.errors + ref_errors
    return CsvValidationReport(valid=len(all_errors) == 0, errors=all_errors, rows=report.rows)
