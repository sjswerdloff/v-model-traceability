"""Tests for test-code linkage verifier (DC-007).

Every test is linked to a design contract via @pytest.mark.traces.
Tests verify observable behavior: what linkages are found and categorised,
not how the AST parsing or graph queries work internally.
"""

from __future__ import annotations

from pathlib import Path

import kuzu
import pytest

from scripts.verify_test_linkage import (
    LinkageItem,
    LinkageReport,
    _collect_code_linkages,
    verify_test_linkage,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph(tmp_path: Path, *, with_verified_by: bool = True) -> Path:
    """Create a minimal Kuzu graph with optional VERIFIED_BY edges.

    Args:
        tmp_path: Base directory for the database.
        with_verified_by: If True, adds VERIFIED_BY edges for DC-001 and DC-002.

    Returns:
        Path to the created Kuzu database.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "test.kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)

    conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, module STRING, PRIMARY KEY (id))")
    conn.execute("CREATE NODE TABLE TestCase(id STRING, title STRING, pytest_path STRING, PRIMARY KEY (id))")

    conn.execute("CREATE (n:DesignContract {id: 'DC-001', title: 'Contract A', module: 'mod_a.py'})")
    conn.execute("CREATE (n:DesignContract {id: 'DC-002', title: 'Contract B', module: 'mod_b.py'})")

    conn.execute("CREATE (n:TestCase {id: 'TC-001', title: 'Test A', pytest_path: 'tests/test_a.py::TestSuite::test_alpha'})")
    conn.execute("CREATE (n:TestCase {id: 'TC-002', title: 'Test B', pytest_path: 'tests/test_b.py::test_beta'})")

    if with_verified_by:
        conn.execute("CREATE REL TABLE VERIFIED_BY(FROM DesignContract TO TestCase, coverage STRING)")
        conn.execute(
            "MATCH (dc:DesignContract), (tc:TestCase) "
            "WHERE dc.id = 'DC-001' AND tc.id = 'TC-001' "
            "CREATE (dc)-[:VERIFIED_BY {coverage: 'full'}]->(tc)"
        )
        conn.execute(
            "MATCH (dc:DesignContract), (tc:TestCase) "
            "WHERE dc.id = 'DC-002' AND tc.id = 'TC-002' "
            "CREATE (dc)-[:VERIFIED_BY {coverage: 'partial'}]->(tc)"
        )

    return db_path


def _write_test_file(test_dir: Path, filename: str, source: str) -> Path:
    """Write a Python source file into test_dir.

    Args:
        test_dir: Directory where the file is written.
        filename: Name of the file (e.g. "test_foo.py").
        source: Python source content.

    Returns:
        Path to the written file.
    """
    test_dir.mkdir(parents=True, exist_ok=True)
    p = test_dir / filename
    p.write_text(source, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def graph_with_two_linkages(tmp_path: Path) -> Path:
    """Graph with DC-001→TC-001 and DC-002→TC-002 VERIFIED_BY edges."""
    return _make_graph(tmp_path)


@pytest.fixture()
def graph_no_verified_by_table(tmp_path: Path) -> Path:
    """Graph without a VERIFIED_BY table at all."""
    return _make_graph(tmp_path / "sub", with_verified_by=False)


@pytest.fixture()
def test_dir_with_markers(tmp_path: Path) -> Path:
    """Test directory containing files with @pytest.mark.traces markers."""
    test_dir = tmp_path / "tests"

    # File 1: class-based, class has marker → all methods inherit it
    _write_test_file(
        test_dir,
        "test_a.py",
        """\
import pytest


class TestSuite:
    @pytest.mark.traces("DC-001")
    def test_alpha(self) -> None:
        pass

    def test_no_marker(self) -> None:
        pass
""",
    )

    # File 2: module-level function with marker
    _write_test_file(
        test_dir,
        "test_b.py",
        """\
import pytest


@pytest.mark.traces("DC-002")
def test_beta() -> None:
    pass


def test_unlinked() -> None:
    pass
""",
    )

    return test_dir


# ---------------------------------------------------------------------------
# DC-007: Code-side parsing tests
# ---------------------------------------------------------------------------


class TestCollectCodeLinkages:
    """Tests for AST-based marker extraction."""

    @pytest.mark.traces("DC-007")
    def test_finds_method_level_marker(self, test_dir_with_markers: Path) -> None:
        """Contract: method-level @pytest.mark.traces is extracted with full pytest_path."""
        linkages, _ = _collect_code_linkages(test_dir_with_markers)

        paths_and_ids = {(item.pytest_path, item.contract_id) for item in linkages}
        assert ("tests/test_a.py::TestSuite::test_alpha", "DC-001") in paths_and_ids

    @pytest.mark.traces("DC-007")
    def test_finds_module_function_marker(self, test_dir_with_markers: Path) -> None:
        """Contract: module-level function @pytest.mark.traces is extracted."""
        linkages, _ = _collect_code_linkages(test_dir_with_markers)

        paths_and_ids = {(item.pytest_path, item.contract_id) for item in linkages}
        assert ("tests/test_b.py::test_beta", "DC-002") in paths_and_ids

    @pytest.mark.traces("DC-007")
    def test_unlinked_methods_reported(self, test_dir_with_markers: Path) -> None:
        """Contract: test functions with no markers appear in unlinked list."""
        _, unlinked = _collect_code_linkages(test_dir_with_markers)

        assert any("test_no_marker" in p for p in unlinked)
        assert any("test_unlinked" in p for p in unlinked)

    @pytest.mark.traces("DC-007")
    def test_marked_functions_not_in_unlinked(self, test_dir_with_markers: Path) -> None:
        """Contract: test functions with markers do not appear in unlinked list."""
        _, unlinked = _collect_code_linkages(test_dir_with_markers)

        assert not any("test_alpha" in p for p in unlinked)
        assert not any("test_beta" in p for p in unlinked)

    @pytest.mark.traces("DC-007")
    def test_class_level_marker_inherited_by_all_methods(self, tmp_path: Path) -> None:
        """Contract: class-level marker is inherited by every test method in the class."""
        test_dir = tmp_path / "tests"
        _write_test_file(
            test_dir,
            "test_class_marker.py",
            """\
import pytest


@pytest.mark.traces("DC-001")
class TestAll:
    def test_one(self) -> None:
        pass

    def test_two(self) -> None:
        pass
""",
        )

        linkages, unlinked = _collect_code_linkages(test_dir)

        ids = {(item.pytest_path, item.contract_id) for item in linkages}
        assert ("tests/test_class_marker.py::TestAll::test_one", "DC-001") in ids
        assert ("tests/test_class_marker.py::TestAll::test_two", "DC-001") in ids
        # Neither method has no marker (class provides it)
        assert not any("test_one" in p for p in unlinked)
        assert not any("test_two" in p for p in unlinked)

    @pytest.mark.traces("DC-007")
    def test_multiple_markers_on_same_function(self, tmp_path: Path) -> None:
        """Contract: multiple @pytest.mark.traces on one function each produce a linkage."""
        test_dir = tmp_path / "tests"
        _write_test_file(
            test_dir,
            "test_multi.py",
            """\
import pytest


@pytest.mark.traces("DC-001")
@pytest.mark.traces("DC-002")
def test_multi() -> None:
    pass
""",
        )

        linkages, _ = _collect_code_linkages(test_dir)

        ids = {(item.pytest_path, item.contract_id) for item in linkages}
        assert ("tests/test_multi.py::test_multi", "DC-001") in ids
        assert ("tests/test_multi.py::test_multi", "DC-002") in ids

    @pytest.mark.traces("DC-007")
    def test_empty_test_dir_returns_empty(self, tmp_path: Path) -> None:
        """Contract: empty test directory produces no linkages or unlinked paths."""
        test_dir = tmp_path / "empty_tests"
        test_dir.mkdir()

        linkages, unlinked = _collect_code_linkages(test_dir)

        assert linkages == []
        assert unlinked == []


# ---------------------------------------------------------------------------
# DC-007: Graph-side query tests
# ---------------------------------------------------------------------------


class TestVerifyTestLinkageGraphQueries:
    """Tests for graph → code cross-referencing."""

    @pytest.mark.traces("DC-007")
    def test_matched_when_graph_and_code_agree(self, tmp_path: Path) -> None:
        """Contract: items in both graph and code appear in matched."""
        db_path = _make_graph(tmp_path / "db")

        test_dir = tmp_path / "tests"
        _write_test_file(
            test_dir,
            "test_a.py",
            """\
import pytest


class TestSuite:
    @pytest.mark.traces("DC-001")
    def test_alpha(self) -> None:
        pass
""",
        )
        _write_test_file(
            test_dir,
            "test_b.py",
            """\
import pytest


@pytest.mark.traces("DC-002")
def test_beta() -> None:
    pass
""",
        )

        report = verify_test_linkage(db_path, test_dir)

        matched_pairs = {(item.pytest_path, item.contract_id) for item in report.matched}
        assert ("tests/test_a.py::TestSuite::test_alpha", "DC-001") in matched_pairs
        assert ("tests/test_b.py::test_beta", "DC-002") in matched_pairs

    @pytest.mark.traces("DC-007")
    def test_graph_only_when_code_lacks_marker(self, tmp_path: Path) -> None:
        """Contract: linkage in graph but missing code marker appears in graph_only."""
        db_path = _make_graph(tmp_path / "db")

        # test_dir has only DC-001 marker; DC-002 link is graph-only
        test_dir = tmp_path / "tests"
        _write_test_file(
            test_dir,
            "test_a.py",
            """\
import pytest


class TestSuite:
    @pytest.mark.traces("DC-001")
    def test_alpha(self) -> None:
        pass
""",
        )

        report = verify_test_linkage(db_path, test_dir)

        graph_only_pairs = {(item.pytest_path, item.contract_id) for item in report.graph_only}
        assert ("tests/test_b.py::test_beta", "DC-002") in graph_only_pairs

    @pytest.mark.traces("DC-007")
    def test_code_only_when_graph_lacks_edge(self, tmp_path: Path) -> None:
        """Contract: code marker without graph edge appears in code_only."""
        db_path = _make_graph(tmp_path / "db")

        # Add a marker referencing DC-999 which has no VERIFIED_BY edge
        test_dir = tmp_path / "tests"
        _write_test_file(
            test_dir,
            "test_extra.py",
            """\
import pytest


@pytest.mark.traces("DC-999")
def test_orphan() -> None:
    pass
""",
        )

        report = verify_test_linkage(db_path, test_dir)

        code_only_pairs = {(item.pytest_path, item.contract_id) for item in report.code_only}
        assert ("tests/test_extra.py::test_orphan", "DC-999") in code_only_pairs

    @pytest.mark.traces("DC-007")
    def test_unlinked_functions_reported(self, tmp_path: Path) -> None:
        """Contract: test functions with no markers appear in unlinked."""
        db_path = _make_graph(tmp_path / "db")

        test_dir = tmp_path / "tests"
        _write_test_file(
            test_dir,
            "test_naked.py",
            """\
def test_no_marker_here() -> None:
    pass
""",
        )

        report = verify_test_linkage(db_path, test_dir)

        assert any("test_no_marker_here" in p for p in report.unlinked)

    @pytest.mark.traces("DC-007")
    def test_empty_report_when_graph_has_no_verified_by_table(self, tmp_path: Path) -> None:
        """Contract: no graph linkages when VERIFIED_BY table is absent."""
        db_path = _make_graph(tmp_path / "db", with_verified_by=False)
        test_dir = tmp_path / "tests"
        test_dir.mkdir()

        report = verify_test_linkage(db_path, test_dir)

        assert report.matched == []
        assert report.graph_only == []

    @pytest.mark.traces("DC-007")
    def test_report_has_mismatches_when_gaps_exist(self, tmp_path: Path) -> None:
        """Contract: has_mismatches is True when any category is non-empty."""
        db_path = _make_graph(tmp_path / "db")
        test_dir = tmp_path / "tests"
        test_dir.mkdir()

        # No code markers at all → graph_only will be populated
        report = verify_test_linkage(db_path, test_dir)

        assert report.has_mismatches is True

    @pytest.mark.traces("DC-007")
    def test_report_no_mismatches_when_fully_aligned(self, tmp_path: Path) -> None:
        """Contract: has_mismatches is False when code and graph fully agree and no unlinked."""
        db_path = _make_graph(tmp_path / "db")

        test_dir = tmp_path / "tests"
        _write_test_file(
            test_dir,
            "test_a.py",
            """\
import pytest


class TestSuite:
    @pytest.mark.traces("DC-001")
    def test_alpha(self) -> None:
        pass
""",
        )
        _write_test_file(
            test_dir,
            "test_b.py",
            """\
import pytest


@pytest.mark.traces("DC-002")
def test_beta() -> None:
    pass
""",
        )

        report = verify_test_linkage(db_path, test_dir)

        assert report.has_mismatches is False

    @pytest.mark.traces("DC-007")
    def test_returns_linkage_report_instance(self, tmp_path: Path) -> None:
        """Contract: verify_test_linkage always returns a LinkageReport."""
        db_path = _make_graph(tmp_path / "db")
        test_dir = tmp_path / "tests"
        test_dir.mkdir()

        report = verify_test_linkage(db_path, test_dir)

        assert isinstance(report, LinkageReport)


# ---------------------------------------------------------------------------
# DC-007: Error semantics
# ---------------------------------------------------------------------------


class TestVerifyTestLinkageErrorSemantics:
    """Tests for infrastructure error handling per DC-007."""

    @pytest.mark.traces("DC-007")
    def test_missing_db_raises_file_not_found(self, tmp_path: Path) -> None:
        """Contract: FileNotFoundError if db_path does not exist."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="Database not found"):
            verify_test_linkage(tmp_path / "nonexistent.kuzu", test_dir)

    @pytest.mark.traces("DC-007")
    def test_missing_test_dir_raises_file_not_found(self, tmp_path: Path) -> None:
        """Contract: FileNotFoundError if test_dir does not exist."""
        db_path = _make_graph(tmp_path / "db")

        with pytest.raises(FileNotFoundError, match="Test directory not found"):
            verify_test_linkage(db_path, tmp_path / "nonexistent_tests")

    @pytest.mark.traces("DC-007")
    def test_missing_schema_tables_raises_runtime_error(self, tmp_path: Path) -> None:
        """Contract: RuntimeError if DesignContract or TestCase tables are absent."""
        db_path = tmp_path / "empty.kuzu"
        db = kuzu.Database(str(db_path))
        kuzu.Connection(db)  # creates DB but no tables

        test_dir = tmp_path / "tests"
        test_dir.mkdir()

        with pytest.raises(RuntimeError, match="Missing required tables"):
            verify_test_linkage(db_path, test_dir)

    @pytest.mark.traces("DC-007")
    def test_partial_schema_design_contract_only_raises_runtime_error(self, tmp_path: Path) -> None:
        """Contract: RuntimeError when DesignContract exists but TestCase table is absent."""
        db_path = tmp_path / "partial.kuzu"
        db = kuzu.Database(str(db_path))
        conn = kuzu.Connection(db)
        # Only create DesignContract; omit TestCase
        conn.execute("CREATE NODE TABLE DesignContract(id STRING, title STRING, PRIMARY KEY (id))")

        test_dir = tmp_path / "tests"
        test_dir.mkdir()

        with pytest.raises(RuntimeError, match="Missing required tables"):
            verify_test_linkage(db_path, test_dir)


# ---------------------------------------------------------------------------
# DC-007: LinkageItem dataclass
# ---------------------------------------------------------------------------


class TestLinkageItemDataclass:
    """Tests for LinkageItem and LinkageReport dataclass contracts."""

    @pytest.mark.traces("DC-007")
    def test_linkage_item_fields(self) -> None:
        """Contract: LinkageItem has pytest_path and contract_id fields."""
        item = LinkageItem(pytest_path="tests/test_foo.py::test_bar", contract_id="DC-001")

        assert item.pytest_path == "tests/test_foo.py::test_bar"
        assert item.contract_id == "DC-001"

    @pytest.mark.traces("DC-007")
    def test_linkage_item_line_number_default_zero(self) -> None:
        """Contract: LinkageItem.line_number defaults to 0 when not supplied."""
        item = LinkageItem(pytest_path="tests/test_foo.py::test_bar", contract_id="DC-001")

        assert item.line_number == 0

    @pytest.mark.traces("DC-007")
    def test_linkage_item_line_number_stored(self) -> None:
        """Contract: LinkageItem stores a non-default line_number when provided."""
        item = LinkageItem(pytest_path="tests/test_foo.py::test_bar", contract_id="DC-001", line_number=42)

        assert item.line_number == 42

    @pytest.mark.traces("DC-007")
    def test_code_side_linkages_have_nonzero_line_numbers(self, tmp_path: Path) -> None:
        """Contract: code-side items parsed from AST carry non-zero line_number."""
        test_dir = tmp_path / "tests"
        _write_test_file(
            test_dir,
            "test_lines.py",
            """\
import pytest


@pytest.mark.traces("DC-001")
def test_alpha() -> None:
    pass


class TestSuite:
    @pytest.mark.traces("DC-002")
    def test_beta(self) -> None:
        pass
""",
        )

        linkages, _ = _collect_code_linkages(test_dir)

        assert len(linkages) >= 2
        for item in linkages:
            assert item.line_number > 0, f"Expected non-zero line_number for {item.pytest_path}"

    @pytest.mark.traces("DC-007")
    def test_linkage_report_default_empty(self) -> None:
        """Contract: LinkageReport initialises all lists empty."""
        report = LinkageReport()

        assert report.matched == []
        assert report.graph_only == []
        assert report.code_only == []
        assert report.unlinked == []
        assert report.has_mismatches is False


# ---------------------------------------------------------------------------
# DC-007: Self-application test
# ---------------------------------------------------------------------------


class TestVerifyTestLinkageSelfApplication:
    """Run DC-007 against the project's own graph and test files."""

    @pytest.mark.traces("DC-007")
    def test_self_application_runs_without_error(self, tmp_path: Path) -> None:
        """Contract: verifier runs successfully against this project's own graph and tests."""
        from scripts.build_graph import build_graph

        project_root = Path(__file__).parent.parent
        build_report = build_graph(
            csv_dir=project_root / "traceability",
            schema_dir=project_root / "schemas",
            output_path=tmp_path / "project.kuzu",
        )
        assert build_report.success

        report = verify_test_linkage(
            db_path=tmp_path / "project.kuzu",
            test_dir=project_root / "tests",
        )

        assert isinstance(report, LinkageReport)
        # The CSV test_cases.csv contains stale class names that no longer match the
        # actual test classes (e.g. TestSchemaValidator → TestValidateSchema,
        # TestGraphBuild → TestBuildGraph).  These graph-side entries can never match
        # any code-side marker, so graph_only must be non-empty — proving the tool
        # correctly detects the drift between CSV metadata and live test code.
        assert len(report.graph_only) > 0, "Expected stale CSV entries to appear in graph_only"
        stale_paths = {item.pytest_path for item in report.graph_only}
        assert any("TestSchemaValidator" in p or "TestGraphBuild" in p for p in stale_paths), (
            f"Expected stale class names in graph_only paths, got: {stale_paths}"
        )

    @pytest.mark.traces("DC-007")
    def test_self_application_finds_code_markers(self, tmp_path: Path) -> None:
        """Contract: verifier detects @pytest.mark.traces markers in this project's test files."""
        from scripts.build_graph import build_graph

        project_root = Path(__file__).parent.parent
        build_graph(
            csv_dir=project_root / "traceability",
            schema_dir=project_root / "schemas",
            output_path=tmp_path / "project.kuzu",
        )

        report = verify_test_linkage(
            db_path=tmp_path / "project.kuzu",
            test_dir=project_root / "tests",
        )

        # All test files in this project use @pytest.mark.traces so code_only or matched
        # must include DC-007 (from this very test file).
        all_code_contracts = {item.contract_id for item in report.matched + report.code_only}
        assert "DC-007" in all_code_contracts
