"""Graph Build Pipeline for V-model traceability framework.

DC-003: Builds a Kuzu graph database from validated CSV inputs.

Guarantees:
- Idempotent: running twice with identical CSVs produces identical graph
- Reproducible: no external state required beyond CSVs
- Validates all CSVs (DC-001 + DC-002) before any graph writes
- Atomic: removes partial build on failure
- Node counts match CSV row counts (verifiable post-build)

Usage:
    from scripts.build_graph import build_graph, BuildReport
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import kuzu

from scripts.validate_csv import (
    CsvSchema,
    CsvValidationReport,
    parse_schema,
    validate_references,
    validate_schema,
)


@dataclass
class BuildReport:
    """Result of graph build pipeline."""

    db_path: Path
    tables_created: dict[str, int] = field(default_factory=dict)
    tables_skipped: list[str] = field(default_factory=list)
    validation_errors: list[CsvValidationReport] = field(default_factory=list)
    success: bool = False


def _schema_stem_to_node_table(stem: str) -> str:
    """Convert schema stem to PascalCase node table name.

    Args:
        stem: Schema filename stem (e.g., "design_contract").

    Returns:
        PascalCase table name (e.g., "DesignContract").
    """
    return "".join(part.capitalize() for part in stem.split("_"))


def _schema_stem_to_edge_table(stem: str) -> str:
    """Convert schema stem to UPPER_SNAKE edge table name.

    Args:
        stem: Schema filename stem (e.g., "fulfilled_by").

    Returns:
        UPPER_SNAKE table name (e.g., "FULFILLED_BY").
    """
    return stem.upper()


def _node_type_to_table_name(node_type: str) -> str:
    """Convert a node type from references annotation to PascalCase table name.

    Args:
        node_type: Node type from references (e.g., "design_contract").

    Returns:
        PascalCase table name (e.g., "DesignContract").
    """
    return _schema_stem_to_node_table(node_type)


def build_graph(
    csv_dir: Path,
    schema_dir: Path,
    output_path: Path,
) -> BuildReport:
    """Build a Kuzu graph database from validated CSV inputs.

    Args:
        csv_dir: Directory containing node and edge CSV files.
        schema_dir: Directory containing .csvschema files (nodes/ and edges/ subdirs).
        output_path: Path for the Kuzu database directory.

    Returns:
        BuildReport with build results or validation errors.
    """
    report = BuildReport(db_path=output_path)

    # Phase 1: Discover schemas and pair with CSVs
    node_schemas: dict[str, tuple[CsvSchema, Path, Path]] = {}  # stem -> (schema, schema_path, csv_path)
    edge_schemas: dict[str, tuple[CsvSchema, Path, Path]] = {}  # stem -> (schema, schema_path, csv_path)

    nodes_dir = schema_dir / "nodes"
    edges_dir = schema_dir / "edges"

    # Scan node schemas
    if nodes_dir.exists():
        for schema_path in sorted(nodes_dir.glob("*.csvschema")):
            schema = parse_schema(schema_path)
            stem = schema_path.stem
            if schema.csv_file:
                csv_path = csv_dir / schema.csv_file
                if csv_path.exists():
                    node_schemas[stem] = (schema, schema_path, csv_path)
                else:
                    report.tables_skipped.append(_schema_stem_to_node_table(stem))
            else:
                report.tables_skipped.append(_schema_stem_to_node_table(stem))

    # Scan edge schemas
    if edges_dir.exists():
        for schema_path in sorted(edges_dir.glob("*.csvschema")):
            schema = parse_schema(schema_path)
            stem = schema_path.stem
            if schema.csv_file:
                csv_path = csv_dir / schema.csv_file
                if csv_path.exists():
                    edge_schemas[stem] = (schema, schema_path, csv_path)
                else:
                    report.tables_skipped.append(_schema_stem_to_edge_table(stem))
            else:
                report.tables_skipped.append(_schema_stem_to_edge_table(stem))

    # Phase 2: Validate all CSVs (DC-001 schema validation)
    node_data: dict[str, list[dict[str, str]]] = {}  # stem -> validated rows
    node_schema_map: dict[str, CsvSchema] = {}  # stem -> schema

    for stem, (schema, schema_path, csv_path) in node_schemas.items():
        node_report = validate_schema(csv_path, schema_path)
        if not node_report.valid:
            report.validation_errors.append(node_report)
        else:
            node_data[stem] = node_report.rows
            node_schema_map[stem] = schema

    # Phase 3: Validate edge references (DC-002 reference integrity)
    edge_data: dict[str, list[dict[str, str]]] = {}  # stem -> validated rows

    for stem, (schema, schema_path, csv_path) in edge_schemas.items():
        edge_report = validate_references(
            csv_path, schema_path, node_data, node_schema_map
        )
        if not edge_report.valid:
            report.validation_errors.append(edge_report)
        else:
            edge_data[stem] = edge_report.rows

    # If any validation failed, stop before building
    if report.validation_errors:
        return report

    # Phase 4: Build the graph (atomic - remove on failure)
    # Idempotent: remove existing database first
    if output_path.exists():
        if output_path.is_dir():
            shutil.rmtree(output_path)
        else:
            output_path.unlink()

    try:
        db = kuzu.Database(str(output_path))
        conn = kuzu.Connection(db)

        # Create node tables and import data
        for stem, (schema, _schema_path, _csv_path) in node_schemas.items():
            table_name = _schema_stem_to_node_table(stem)
            columns = ", ".join(
                f"{col} STRING" for col in schema.headers
            )
            conn.execute(f"CREATE NODE TABLE {table_name}({columns}, PRIMARY KEY ({schema.id_field}))")

            # Insert rows
            row_count = 0
            for row in node_data[stem]:
                values = ", ".join(
                    f"'{_escape_cypher(row.get(col, ''))}'" for col in schema.headers
                )
                conn.execute(f"CREATE (n:{table_name} {{{_props_cypher(schema.headers, row)}}})")
                row_count += 1
            report.tables_created[table_name] = row_count

        # Create edge tables and import data
        for stem, (schema, _schema_path, _csv_path) in edge_schemas.items():
            table_name = _schema_stem_to_edge_table(stem)

            # Determine FROM and TO from references
            ref_items = list(schema.references.items())
            if len(ref_items) < 2:
                continue

            from_col, from_type = ref_items[0]
            to_col, to_type = ref_items[1]
            from_table = _node_type_to_table_name(from_type)
            to_table = _node_type_to_table_name(to_type)

            # Non-FK columns for edge properties
            prop_cols = [
                col for col in schema.headers
                if col not in schema.references
            ]
            props_def = ", ".join(f"{col} STRING" for col in prop_cols)
            if props_def:
                conn.execute(
                    f"CREATE REL TABLE {table_name}(FROM {from_table} TO {to_table}, {props_def})"
                )
            else:
                conn.execute(
                    f"CREATE REL TABLE {table_name}(FROM {from_table} TO {to_table})"
                )

            # Insert edges
            row_count = 0
            for row in edge_data[stem]:
                from_id = _escape_cypher(row.get(from_col, ""))
                to_id = _escape_cypher(row.get(to_col, ""))

                from_schema = node_schema_map[from_type]
                to_schema = node_schema_map[to_type]

                if prop_cols:
                    props = ", ".join(
                        f"r.{col} = '{_escape_cypher(row.get(col, ''))}'"
                        for col in prop_cols
                    )
                    conn.execute(
                        f"MATCH (a:{from_table}), (b:{to_table}) "
                        f"WHERE a.{from_schema.id_field} = '{from_id}' "
                        f"AND b.{to_schema.id_field} = '{to_id}' "
                        f"CREATE (a)-[r:{table_name}]->(b) SET {props}"
                    )
                else:
                    conn.execute(
                        f"MATCH (a:{from_table}), (b:{to_table}) "
                        f"WHERE a.{from_schema.id_field} = '{from_id}' "
                        f"AND b.{to_schema.id_field} = '{to_id}' "
                        f"CREATE (a)-[r:{table_name}]->(b)"
                    )
                row_count += 1
            report.tables_created[table_name] = row_count

        report.success = True

    except Exception:
        # Atomic: remove partial build on failure
        if output_path.exists():
            shutil.rmtree(output_path)
        raise

    return report


def _escape_cypher(value: str) -> str:
    """Escape a string value for Cypher queries.

    Args:
        value: Raw string value.

    Returns:
        Escaped string safe for single-quoted Cypher literals.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _props_cypher(headers: list[str], row: dict[str, str]) -> str:
    """Build a Cypher property map from headers and a row dict.

    Args:
        headers: Column names.
        row: Row data dict.

    Returns:
        Cypher property map string (e.g., "id: 'REQ-001', title: 'Foo'").
    """
    parts = []
    for col in headers:
        val = _escape_cypher(row.get(col, ""))
        parts.append(f"{col}: '{val}'")
    return ", ".join(parts)
