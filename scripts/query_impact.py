"""Impact Analysis Query for V-model traceability framework.

DC-005: Given a contract_id, finds all directly connected tests, requirements,
and impacted/impacting contracts via VERIFIED_BY, FULFILLED_BY, and IMPACTS edges.

Guarantees:
- Traverses all 3 edge types (VERIFIED_BY, FULFILLED_BY, IMPACTS)
- Direct edges only (transitive traversal is v2)
- Deterministically ordered output (by ID)

Error semantics:
- Fails on missing contract_id (ValueError)
- Fails on missing or corrupt database (FileNotFoundError, RuntimeError)

Usage:
    from scripts.query_impact import query_impact, ImpactReport
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import kuzu


@dataclass
class ImpactItem:
    """A single node reachable from a contract via one edge type."""

    id: str
    title: str
    edge_type: str
    direction: str = ""


@dataclass
class ImpactReport:
    """Result of an impact analysis query for a single design contract."""

    contract_id: str
    contract_title: str
    direct_tests: list[ImpactItem] = field(default_factory=list)
    fulfilled_requirements: list[ImpactItem] = field(default_factory=list)
    impacted_contracts: list[ImpactItem] = field(default_factory=list)

    @property
    def total_connections(self) -> int:
        """Total number of direct connections across all edge types."""
        return len(self.direct_tests) + len(self.fulfilled_requirements) + len(self.impacted_contracts)


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


def query_impact(db_path: Path, contract_id: str) -> ImpactReport:
    """Find all directly connected tests, requirements, and contracts for a contract.

    Args:
        db_path: Path to Kuzu database.
        contract_id: ID of the DesignContract to analyze.

    Returns:
        ImpactReport with direct_tests, fulfilled_requirements, and impacted_contracts.

    Raises:
        FileNotFoundError: If database path doesn't exist.
        RuntimeError: If expected schema is missing (DesignContract, edge tables, or endpoint tables).
        ValueError: If contract_id is not found in the database.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    missing = _verify_schema(conn, ["DesignContract"])
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")

    # Verify the contract exists
    result = conn.execute(
        "MATCH (dc:DesignContract) WHERE dc.id = $cid RETURN dc.id, dc.title",
        {"cid": contract_id},
    )
    if not result.has_next():
        raise ValueError(f"DesignContract not found: {contract_id}")

    row = result.get_next()
    contract_title: str = row[1]
    report = ImpactReport(contract_id=contract_id, contract_title=contract_title)

    # Verify all required edge tables exist — incomplete graph is a fatal error
    # for impact analysis (false negatives mask real impacts)
    edge_missing = _verify_schema(conn, ["VERIFIED_BY", "TestCase", "FULFILLED_BY", "Requirement", "IMPACTS"])
    if edge_missing:
        raise RuntimeError(
            f"Incomplete graph for impact analysis: missing {edge_missing}. "
            "A silent empty result could mask real impacts."
        )

    # Query 1: Direct tests via VERIFIED_BY (DesignContract → TestCase)
    result = conn.execute(
        "MATCH (dc:DesignContract)-[:VERIFIED_BY]->(tc:TestCase) WHERE dc.id = $cid RETURN tc.id, tc.title ORDER BY tc.id",
        {"cid": contract_id},
    )
    while result.has_next():
        row = result.get_next()
        report.direct_tests.append(ImpactItem(id=row[0], title=row[1], edge_type="VERIFIED_BY", direction="outbound"))

    # Query 2: Requirements fulfilled by this contract via FULFILLED_BY
    # Direction: FULFILLED_BY goes FROM Requirement TO DesignContract
    result = conn.execute(
        "MATCH (r:Requirement)-[:FULFILLED_BY]->(dc:DesignContract) WHERE dc.id = $cid RETURN r.id, r.title ORDER BY r.id",
        {"cid": contract_id},
    )
    while result.has_next():
        row = result.get_next()
        report.fulfilled_requirements.append(
            ImpactItem(id=row[0], title=row[1], edge_type="FULFILLED_BY", direction="inbound")
        )

    # Query 3: Contracts connected via IMPACTS edges (both directions)
        # Outbound: this contract impacts others
        result = conn.execute(
            "MATCH (dc:DesignContract)-[:IMPACTS]->(other:DesignContract) "
            "WHERE dc.id = $cid "
            "RETURN other.id, other.title "
            "ORDER BY other.id",
            {"cid": contract_id},
        )
        while result.has_next():
            row = result.get_next()
            report.impacted_contracts.append(ImpactItem(id=row[0], title=row[1], edge_type="IMPACTS", direction="outbound"))

        # Inbound: other contracts impact this one
        result = conn.execute(
            "MATCH (other:DesignContract)-[:IMPACTS]->(dc:DesignContract) "
            "WHERE dc.id = $cid "
            "RETURN other.id, other.title "
            "ORDER BY other.id",
            {"cid": contract_id},
        )
        while result.has_next():
            row = result.get_next()
            report.impacted_contracts.append(ImpactItem(id=row[0], title=row[1], edge_type="IMPACTS", direction="inbound"))

    return report
