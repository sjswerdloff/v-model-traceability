"""Test-Code Linkage Verifier for V-model traceability framework.

DC-007: Cross-references TestCase → DesignContract edges in the Kuzu graph
against @pytest.mark.traces("DC-XXX") markers found in actual test source files.

Guarantees:
- Both directions checked: graph_only and code_only gaps are both reported
- AST-based parsing of test files (no import or execution required)
- Actionable output: matched, graph_only, code_only, unlinked sets
- Class-level markers are inherited by all test methods in that class

Error semantics:
- Advisory: returns LinkageReport even when mismatches exist (exit 0)
- Non-zero / raises only for infrastructure errors (missing DB, missing test_dir)

Usage:
    from scripts.verify_test_linkage import verify_test_linkage, LinkageReport
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import kuzu


@dataclass
class LinkageItem:
    """A single test-to-contract linkage found in one source."""

    pytest_path: str
    contract_id: str
    line_number: int = 0


@dataclass
class LinkageReport:
    """Result of cross-referencing graph linkages against code markers.

    Attributes:
        matched: pytest_paths that appear in both graph and code markers.
        graph_only: linkages in graph but no corresponding code marker found.
        code_only: code markers that have no corresponding graph edge.
        unlinked: pytest_paths of test functions with no markers at all.
    """

    matched: list[LinkageItem] = field(default_factory=list)
    graph_only: list[LinkageItem] = field(default_factory=list)
    code_only: list[LinkageItem] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)

    @property
    def has_mismatches(self) -> bool:
        """True if any linkage gaps exist between graph and code."""
        return bool(self.graph_only or self.code_only or self.unlinked)


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


def _extract_traces_marker_args(decorator: ast.expr) -> list[str]:
    """Extract contract IDs from a @pytest.mark.traces(...) decorator node.

    Handles both ``@pytest.mark.traces("DC-XXX")`` and
    ``@pytest.mark.traces("DC-XXX", "DC-YYY")`` forms.

    Args:
        decorator: An AST expression node for one decorator.

    Returns:
        List of contract ID strings (may be empty if decorator is not traces).
    """
    # We expect: pytest.mark.traces("DC-XXX")
    # AST shape: Call(func=Attribute(value=Attribute(value=Name(id='pytest'), attr='mark'), attr='traces'), ...)
    if not isinstance(decorator, ast.Call):
        return []
    func = decorator.func
    if not (isinstance(func, ast.Attribute) and func.attr == "traces"):
        return []
    # Accept pytest.mark.traces or just mark.traces
    ids: list[str] = []
    for arg in decorator.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            ids.append(arg.value)
    return ids


def _collect_code_linkages(test_dir: Path) -> tuple[list[LinkageItem], list[str]]:
    """Parse test files to extract @pytest.mark.traces markers via AST.

    Class-level markers are inherited by all test methods in that class.

    Args:
        test_dir: Directory to search recursively for test_*.py files.

    Returns:
        Tuple of (linkages, unlinked_paths) where:
          - linkages is a list of LinkageItem for every (pytest_path, contract_id) found.
          - unlinked_paths is a list of pytest_path strings for functions with no markers.
    """
    linkages: list[LinkageItem] = []
    unlinked: list[str] = []

    for test_file in sorted(test_dir.rglob("test_*.py")):
        # Make the path relative to test_dir's parent for stable pytest_path keys
        try:
            rel_path = test_file.relative_to(test_dir.parent)
        except ValueError:
            rel_path = test_file

        rel_str = rel_path.as_posix()

        source = test_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(test_file))

        # Iterate module.body directly to get only true top-level nodes
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                # Collect class-level traces markers
                class_contract_ids: list[str] = []
                for dec in node.decorator_list:
                    class_contract_ids.extend(_extract_traces_marker_args(dec))

                # Walk methods inside the class
                for item in node.body:
                    if not (isinstance(item, ast.FunctionDef) and item.name.startswith("test_")):
                        continue
                    method_path = f"{rel_str}::{node.name}::{item.name}"

                    method_contract_ids: list[str] = []
                    for dec in item.decorator_list:
                        method_contract_ids.extend(_extract_traces_marker_args(dec))

                    all_ids = class_contract_ids + method_contract_ids
                    if all_ids:
                        for cid in all_ids:
                            linkages.append(
                                LinkageItem(
                                    pytest_path=method_path,
                                    contract_id=cid,
                                    line_number=item.lineno,
                                )
                            )
                    else:
                        unlinked.append(method_path)

            elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                # Only top-level test functions (module.body guarantees this)
                func_path = f"{rel_str}::{node.name}"

                func_contract_ids: list[str] = []
                for dec in node.decorator_list:
                    func_contract_ids.extend(_extract_traces_marker_args(dec))

                if func_contract_ids:
                    for cid in func_contract_ids:
                        linkages.append(
                            LinkageItem(
                                pytest_path=func_path,
                                contract_id=cid,
                                line_number=node.lineno,
                            )
                        )
                else:
                    unlinked.append(func_path)

    return linkages, unlinked


def _query_graph_linkages(db_path: Path) -> list[LinkageItem]:
    """Query Kuzu graph for all DesignContract → TestCase VERIFIED_BY edges.

    Args:
        db_path: Path to the Kuzu database.

    Returns:
        List of LinkageItem for each (pytest_path, contract_id) edge in the graph.

    Raises:
        FileNotFoundError: If database path doesn't exist.
        RuntimeError: If expected schema tables are missing.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    missing = _verify_schema(conn, ["DesignContract", "TestCase"])
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")

    # Check if VERIFIED_BY table exists; if not, there are no graph linkages
    edge_missing = _verify_schema(conn, ["VERIFIED_BY"])
    if edge_missing:
        return []

    result = conn.execute(
        "MATCH (dc:DesignContract)-[:VERIFIED_BY]->(tc:TestCase) RETURN dc.id, tc.pytest_path ORDER BY dc.id, tc.pytest_path"
    )

    linkages: list[LinkageItem] = []
    while result.has_next():
        row = result.get_next()
        contract_id: str = row[0]
        pytest_path: str = row[1]
        if pytest_path:
            linkages.append(LinkageItem(pytest_path=pytest_path, contract_id=contract_id))

    return linkages


def verify_test_linkage(db_path: Path, test_dir: Path) -> LinkageReport:
    """Cross-reference graph VERIFIED_BY edges against code @pytest.mark.traces markers.

    Queries the Kuzu DB for TestCase nodes linked to DesignContracts via VERIFIED_BY,
    then parses test source files with AST to find @pytest.mark.traces("DC-XXX") markers.
    Compares both sets to produce a LinkageReport.

    Args:
        db_path: Path to the Kuzu database directory.
        test_dir: Directory containing pytest test files to parse.

    Returns:
        LinkageReport with matched, graph_only, code_only, and unlinked.

    Raises:
        FileNotFoundError: If db_path or test_dir does not exist.
        RuntimeError: If required schema tables are missing from the database.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    if not test_dir.exists():
        raise FileNotFoundError(f"Test directory not found: {test_dir}")

    graph_linkages = _query_graph_linkages(db_path)
    code_linkages, unlinked = _collect_code_linkages(test_dir)

    # Build lookup sets using (pytest_path, contract_id) tuples
    graph_set = {(item.pytest_path, item.contract_id) for item in graph_linkages}
    code_set = {(item.pytest_path, item.contract_id) for item in code_linkages}

    matched_set = graph_set & code_set
    graph_only_set = graph_set - code_set
    code_only_set = code_set - graph_set

    report = LinkageReport(
        matched=sorted([LinkageItem(*pair) for pair in matched_set], key=lambda x: (x.pytest_path, x.contract_id)),
        graph_only=sorted([LinkageItem(*pair) for pair in graph_only_set], key=lambda x: (x.pytest_path, x.contract_id)),
        code_only=sorted([LinkageItem(*pair) for pair in code_only_set], key=lambda x: (x.pytest_path, x.contract_id)),
        unlinked=sorted(set(unlinked)),
    )

    return report


# TODO: Add __main__ CLI entry point (DC-007 contract: non-zero exit for infra errors)
