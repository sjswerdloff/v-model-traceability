"""Gap Analysis Query for V-model traceability framework.

DC-004: Finds design contracts with no VERIFIED_BY edges (untested contracts)
and requirements with no FULFILLED_BY edges (unimplemented requirements).

Guarantees:
- Returns empty list when every contract has at least one test
- Includes contract ID, title, and module in output for actionability
- Output is deterministically ordered (by ID)

Usage:
    from scripts.query_gaps import query_untested_contracts, query_unimplemented_requirements, GapReport
    from scripts.query_gaps import (
        query_empty_bounded_contexts,
        query_unscoped_design_contracts,
        query_domain_terms_without_aliases,
    )
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
    partial_only_contracts: list[GapItem] = field(default_factory=list)
    empty_bounded_contexts: list[GapItem] = field(default_factory=list)
    unscoped_design_contracts: list[GapItem] = field(default_factory=list)
    domain_terms_without_aliases: list[GapItem] = field(default_factory=list)

    @property
    def has_gaps(self) -> bool:
        """True if any traceability gaps exist."""
        return bool(self.untested_contracts or self.unimplemented_requirements or self.empty_bounded_contexts)

    @property
    def has_warnings(self) -> bool:
        """True if any traceability warnings exist (partial-only or DDD advisory)."""
        return bool(self.partial_only_contracts or self.unscoped_design_contracts or self.domain_terms_without_aliases)


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
        result = conn.execute("MATCH (dc:DesignContract) RETURN dc.id, dc.title, dc.module ORDER BY dc.id")
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
        result = conn.execute("MATCH (r:Requirement) RETURN r.id, r.title, r.priority ORDER BY r.id")
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


def query_partial_only_contracts(db_path: Path) -> list[GapItem]:
    """Find design contracts where all verified_by edges are partial (no full coverage).

    These are contracts that have tests but none provide full coverage —
    the test requirements span multiple DCs. May indicate coverage gaps
    even though edges exist.

    Args:
        db_path: Path to Kuzu database.

    Returns:
        List of GapItems for partial-only contracts, ordered by ID.

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

    edge_missing = _verify_schema(conn, ["VERIFIED_BY"])
    if edge_missing:
        return []  # No edges at all — untested_contracts handles this

    result = conn.execute(
        "MATCH (dc:DesignContract) "
        "WHERE EXISTS { MATCH (dc)-[:VERIFIED_BY]->(:TestCase) } "
        "AND NOT EXISTS { MATCH (dc)-[e:VERIFIED_BY]->(:TestCase) WHERE e.coverage = 'full' } "
        "RETURN dc.id, dc.title, dc.module "
        "ORDER BY dc.id"
    )

    gaps = []
    while result.has_next():
        row = result.get_next()
        gaps.append(GapItem(id=row[0], title=row[1], module=row[2] or ""))

    return gaps


def query_empty_bounded_contexts(db_path: Path) -> list[GapItem]:
    """Find BoundedContexts that have no DesignContracts pointing to them.

    Gracefully returns an empty list if the BoundedContext table does not exist,
    supporting projects that have not yet adopted DDD.

    Args:
        db_path: Path to Kuzu database.

    Returns:
        List of GapItems for empty bounded contexts, ordered by ID.

    Raises:
        FileNotFoundError: If database path doesn't exist.
        RuntimeError: If DesignContract table is missing (required for the join check).
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    # Graceful: DDD tables may not exist yet
    if _verify_schema(conn, ["BoundedContext"]):
        return []

    missing = _verify_schema(conn, ["DesignContract"])
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")

    result = conn.execute(
        "MATCH (bc:BoundedContext) "
        "WHERE NOT EXISTS { MATCH (dc:DesignContract) WHERE dc.bounded_context_id = bc.id } "
        "RETURN bc.id, bc.name, bc.purpose "
        "ORDER BY bc.id"
    )

    gaps = []
    while result.has_next():
        row = result.get_next()
        gaps.append(GapItem(id=row[0], title=row[1], module=row[2] or ""))

    return gaps


def query_unscoped_design_contracts(db_path: Path) -> list[GapItem]:
    """Find DesignContracts with empty bounded_context_id.

    Gracefully returns an empty list if the BoundedContext table does not exist,
    supporting projects that have not yet adopted DDD.

    Args:
        db_path: Path to Kuzu database.

    Returns:
        List of GapItems for unscoped design contracts, ordered by ID.

    Raises:
        FileNotFoundError: If database path doesn't exist.
        RuntimeError: If DesignContract table is missing.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    # Graceful: DDD tables may not exist yet
    if _verify_schema(conn, ["BoundedContext"]):
        return []

    missing = _verify_schema(conn, ["DesignContract"])
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")

    result = conn.execute(
        "MATCH (dc:DesignContract) "
        "WHERE dc.bounded_context_id IS NULL OR dc.bounded_context_id = '' "
        "RETURN dc.id, dc.title, dc.module "
        "ORDER BY dc.id"
    )

    gaps = []
    while result.has_next():
        row = result.get_next()
        gaps.append(GapItem(id=row[0], title=row[1], module=row[2] or ""))

    return gaps


def query_domain_terms_without_aliases(db_path: Path) -> list[GapItem]:
    """Find DomainTerms where aliases_to_avoid is empty.

    These glossary entries exist but don't prevent term conflation.
    Gracefully returns an empty list if the DomainTerm table does not exist.

    Args:
        db_path: Path to Kuzu database.

    Returns:
        List of GapItems for domain terms without aliases, ordered by ID.

    Raises:
        FileNotFoundError: If database path doesn't exist.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    # Graceful: DDD tables may not exist yet
    if _verify_schema(conn, ["DomainTerm"]):
        return []

    result = conn.execute(
        "MATCH (dt:DomainTerm) "
        "WHERE dt.aliases_to_avoid IS NULL OR dt.aliases_to_avoid = '' "
        "RETURN dt.id, dt.term, dt.bounded_context "
        "ORDER BY dt.id"
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
        GapReport with untested contracts, unimplemented requirements,
        partial-only contracts, and DDD gap analysis results.
    """
    report = GapReport()
    report.untested_contracts = query_untested_contracts(db_path)
    report.unimplemented_requirements = query_unimplemented_requirements(db_path)
    report.partial_only_contracts = query_partial_only_contracts(db_path)
    report.empty_bounded_contexts = query_empty_bounded_contexts(db_path)
    report.unscoped_design_contracts = query_unscoped_design_contracts(db_path)
    report.domain_terms_without_aliases = query_domain_terms_without_aliases(db_path)
    return report
