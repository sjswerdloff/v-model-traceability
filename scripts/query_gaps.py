"""Gap Analysis Query for V-model traceability framework.

DC-004: Finds design contracts with no VERIFIED_BY edges (untested contracts)
and requirements with no FULFILLED_BY edges (unimplemented requirements).

Guarantees:
- Returns empty list when every contract has at least one test
- Includes contract ID, title, and module in output for actionability
- Output is deterministically ordered (by ID)

Usage:
    from scripts.query_gaps import query_untested_contracts, query_unimplemented_requirements, GapReport
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import kuzu


@dataclass
class GapItem:
    """A single item missing traceability coverage."""

    id: str
    title: str
    module: str = ""


@dataclass
class GapReport:
    """Result of gap analysis queries."""

    untested_contracts: list[GapItem] = field(default_factory=list)
    unimplemented_requirements: list[GapItem] = field(default_factory=list)

    @property
    def has_gaps(self) -> bool:
        """True if any traceability gaps exist."""
        return bool(self.untested_contracts or self.unimplemented_requirements)


def _verify_schema(conn: kuzu.Connection, required_tables: list[str]) -> list[str]:
    """Check that expected tables exist in the database.

    Args:
        conn: Kuzu connection.
        required_tables: Table names to check.

    Returns:
        List of missing table names (empty if all present).
    """
    result = conn.execute("CALL show_tables() RETURN name")
    existing = set()
    while result.has_next():
        existing.add(result.get_next()[0])
    return [t for t in required_tables if t not in existing]


def query_untested_contracts(db_path: Path) -> list[GapItem]:
    """Find design contracts with no VERIFIED_BY edges.

    Args:
        db_path: Path to Kuzu database.

    Returns:
        List of GapItems for untested contracts, ordered by ID.

    Raises:
        FileNotFoundError: If database path doesn't exist.
        RuntimeError: If expected schema is missing.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    missing = _verify_schema(conn, ["DesignContract"])
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")

    # Check if VERIFIED_BY edge table exists — if not, ALL contracts are untested
    edge_missing = _verify_schema(conn, ["VERIFIED_BY"])
    if edge_missing:
        result = conn.execute(
            "MATCH (dc:DesignContract) "
            "RETURN dc.id, dc.title, dc.module "
            "ORDER BY dc.id"
        )
        gaps = []
        while result.has_next():
            row = result.get_next()
            gaps.append(GapItem(id=row[0], title=row[1], module=row[2] or ""))
        return gaps

    # Find contracts with zero VERIFIED_BY edges
    result = conn.execute(
        "MATCH (dc:DesignContract) "
        "WHERE NOT EXISTS { MATCH (dc)-[:VERIFIED_BY]->(:TestCase) } "
        "RETURN dc.id, dc.title, dc.module "
        "ORDER BY dc.id"
    )

    gaps = []
    while result.has_next():
        row = result.get_next()
        gaps.append(GapItem(id=row[0], title=row[1], module=row[2] or ""))

    return gaps


def query_unimplemented_requirements(db_path: Path) -> list[GapItem]:
    """Find requirements with no FULFILLED_BY edges.

    Args:
        db_path: Path to Kuzu database.

    Returns:
        List of GapItems for unimplemented requirements, ordered by ID.

    Raises:
        FileNotFoundError: If database path doesn't exist.
        RuntimeError: If expected schema is missing.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    missing = _verify_schema(conn, ["Requirement"])
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")

    edge_missing = _verify_schema(conn, ["FULFILLED_BY"])
    if edge_missing:
        result = conn.execute(
            "MATCH (r:Requirement) "
            "RETURN r.id, r.title, r.priority "
            "ORDER BY r.id"
        )
        gaps = []
        while result.has_next():
            row = result.get_next()
            gaps.append(GapItem(id=row[0], title=row[1], module=row[2] or ""))
        return gaps

    result = conn.execute(
        "MATCH (r:Requirement) "
        "WHERE NOT EXISTS { MATCH (r)-[:FULFILLED_BY]->(:DesignContract) } "
        "RETURN r.id, r.title, r.priority "
        "ORDER BY r.id"
    )

    gaps = []
    while result.has_next():
        row = result.get_next()
        gaps.append(GapItem(id=row[0], title=row[1], module=row[2] or ""))

    return gaps


def run_gap_analysis(db_path: Path) -> GapReport:
    """Run full gap analysis on a traceability graph.

    Args:
        db_path: Path to Kuzu database.

    Returns:
        GapReport with untested contracts and unimplemented requirements.
    """
    report = GapReport()
    report.untested_contracts = query_untested_contracts(db_path)
    report.unimplemented_requirements = query_unimplemented_requirements(db_path)
    return report
