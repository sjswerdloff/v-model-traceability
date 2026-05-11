"""Tests for the edge CSV generator (fulfilled_by.csv and verified_by.csv).

Requirements coverage: EDGE-REQ-001 through EDGE-REQ-073.
Golden dataset: python-tesseron/traceability/ hand-written edge CSVs.

Every MUST requirement has at least one positive test.
Every MUST NOT requirement has at least one negative test.
Every SHOULD requirement has at least one positive test.

Tests requiring the generator implementation are marked xfail.
"""

from __future__ import annotations

import csv
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

TESSERON_TRACEABILITY = Path(
    "/Users/stuartswerdloff/ai/ClaudeInstanceHomeOffices/cyril-9137f1ee/kindled_projects/python-tesseron/traceability"
)

TESSERON_TESTS = Path(
    "/Users/stuartswerdloff/ai/ClaudeInstanceHomeOffices/cyril-9137f1ee/kindled_projects/python-tesseron/tests"
)

TESSERON_SRC = Path("/Users/stuartswerdloff/ai/ClaudeInstanceHomeOffices/cyril-9137f1ee/kindled_projects/python-tesseron/src")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    """Write a list of row dicts to a CSV file with the keys as header."""
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into a list of row dicts."""
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Fixtures — synthetic minimal traceability datasets
# ---------------------------------------------------------------------------


@pytest.fixture()
def traceability_dir(tmp_path: Path) -> Path:
    """Create a minimal synthetic traceability directory.

    Contains:
    - requirements.csv  (REQ-001 through REQ-004)
    - design_contracts.csv  (DC-001, DC-002 with embedded REQ references)
    - test_cases.csv  (AT-01, WF-01)
    """
    trace_dir = tmp_path / "traceability"
    trace_dir.mkdir()

    _write_csv(
        trace_dir / "requirements.csv",
        [
            {
                "id": "REQ-001",
                "title": "Req one",
                "description": "desc",
                "priority": "high",
                "status": "draft",
                "source": "spec",
            },
            {
                "id": "REQ-002",
                "title": "Req two",
                "description": "desc",
                "priority": "high",
                "status": "draft",
                "source": "spec",
            },
            {
                "id": "REQ-003",
                "title": "Req three",
                "description": "desc",
                "priority": "medium",
                "status": "draft",
                "source": "spec",
            },
            {
                "id": "REQ-004",
                "title": "Req four",
                "description": "desc",
                "priority": "low",
                "status": "draft",
                "source": "spec",
            },
        ],
    )

    _write_csv(
        trace_dir / "design_contracts.csv",
        [
            {
                "id": "DC-001",
                "title": "Dispatcher",
                "module": "pkg/dispatcher.py",
                "inputs": "requests",
                "outputs": "responses",
                "guarantees": "Fulfils REQ-001 and REQ-002",
                "error_semantics": "raises on REQ-003",
                "status": "draft",
            },
            {
                "id": "DC-002",
                "title": "Transport",
                "module": "pkg/transport.py",
                "inputs": "connections",
                "outputs": "frames",
                "guarantees": "Satisfies REQ-002 and REQ-004",
                "error_semantics": "none",
                "status": "draft",
            },
        ],
    )

    _write_csv(
        trace_dir / "test_cases.csv",
        [
            {
                "id": "AT-01",
                "title": "Basic discovery",
                "pytest_path": "tests/test_acceptance.py::test_at01",
                "test_type": "acceptance",
                "status": "passing",
            },
            {
                "id": "WF-01",
                "title": "Request shape",
                "pytest_path": "tests/test_wire_format.py::test_wf01",
                "test_type": "wire_format",
                "status": "passing",
            },
        ],
    )

    return trace_dir


@pytest.fixture()
def tests_dir(tmp_path: Path) -> Path:
    """Create a synthetic tests directory with test functions containing docstrings."""
    tests = tmp_path / "tests"
    tests.mkdir()

    (tests / "__init__.py").write_text("")

    # AT-01 references REQ-001 → DC-001 (full coverage)
    # WF-01 references REQ-002 → DC-001 and DC-002 (partial coverage — spans two DCs)
    (tests / "test_acceptance.py").write_text(
        textwrap.dedent('''\
            """Acceptance tests."""

            import pytest


            def test_at01():
                """AT-01: REQ-001. Basic discovery scenario.

                Verifies that REQ-001 is satisfied by DC-001.
                """
                pass
        ''')
    )

    (tests / "test_wire_format.py").write_text(
        textwrap.dedent('''\
            """Wire format tests."""

            import pytest


            def test_wf01():
                """WF-01: REQ-002. Request shape must have all fields.

                Verifies REQ-002 which spans DC-001 and DC-002.
                """
                pass
        ''')
    )

    return tests


@pytest.fixture()
def src_dir(tmp_path: Path) -> Path:
    """Create a synthetic src directory with module docstrings containing REQ references."""
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)

    (src / "__init__.py").write_text("")

    # Module docstring references REQ-001 — associated with DC-001 via module field
    (src / "dispatcher.py").write_text(
        textwrap.dedent('''\
            """Dispatcher module.

            Implements REQ-001: The dispatcher must route all incoming requests.
            """


            class Dispatcher:
                pass
        ''')
    )

    # Module docstring references REQ-004 — associated with DC-002 via module field
    (src / "transport.py").write_text(
        textwrap.dedent('''\
            """Transport module.

            Implements REQ-004: The transport must accept exactly one connection.
            """


            class Transport:
                pass
        ''')
    )

    return tmp_path / "src"


@pytest.fixture()
def traceability_dir_no_req_refs(tmp_path: Path) -> Path:
    """Traceability dir where one DC has no REQ references in any field."""
    trace_dir = tmp_path / "traceability"
    trace_dir.mkdir()

    _write_csv(
        trace_dir / "requirements.csv",
        [{"id": "REQ-001", "title": "R1", "description": "d", "priority": "high", "status": "draft", "source": "s"}],
    )

    _write_csv(
        trace_dir / "design_contracts.csv",
        [
            {
                "id": "DC-001",
                "title": "WithRef",
                "module": "pkg/a.py",
                "inputs": "",
                "outputs": "",
                "guarantees": "implements REQ-001",
                "error_semantics": "",
                "status": "draft",
            },
            {
                "id": "DC-002",
                "title": "NoRef",
                "module": "pkg/b.py",
                "inputs": "",
                "outputs": "",
                "guarantees": "no requirement references here",
                "error_semantics": "",
                "status": "draft",
            },
        ],
    )

    _write_csv(
        trace_dir / "test_cases.csv",
        [{"id": "AT-01", "title": "t", "pytest_path": "tests/t.py::t", "test_type": "acceptance", "status": "passing"}],
    )

    return trace_dir


@pytest.fixture()
def traceability_dir_phantom_req(tmp_path: Path) -> Path:
    """Traceability dir where a DC text references a REQ not in requirements.csv."""
    trace_dir = tmp_path / "traceability"
    trace_dir.mkdir()

    _write_csv(
        trace_dir / "requirements.csv",
        [{"id": "REQ-001", "title": "R1", "description": "d", "priority": "high", "status": "draft", "source": "s"}],
    )

    _write_csv(
        trace_dir / "design_contracts.csv",
        [
            {
                "id": "DC-001",
                "title": "WithPhantom",
                "module": "pkg/a.py",
                "inputs": "",
                "outputs": "",
                "guarantees": "implements REQ-001 and REQ-999",
                "error_semantics": "",
                "status": "draft",
            },
        ],
    )

    _write_csv(
        trace_dir / "test_cases.csv",
        [{"id": "AT-01", "title": "t", "pytest_path": "tests/t.py::t", "test_type": "acceptance", "status": "passing"}],
    )

    return trace_dir


@pytest.fixture()
def traceability_dir_duplicate_ref(tmp_path: Path) -> Path:
    """Traceability dir where a single DC mentions the same REQ twice in one field."""
    trace_dir = tmp_path / "traceability"
    trace_dir.mkdir()

    _write_csv(
        trace_dir / "requirements.csv",
        [{"id": "REQ-001", "title": "R1", "description": "d", "priority": "high", "status": "draft", "source": "s"}],
    )

    _write_csv(
        trace_dir / "design_contracts.csv",
        [
            {
                "id": "DC-001",
                "title": "DoubleRef",
                "module": "pkg/a.py",
                "inputs": "REQ-001",
                "outputs": "",
                "guarantees": "implements REQ-001 again",
                "error_semantics": "",
                "status": "draft",
            },
        ],
    )

    _write_csv(
        trace_dir / "test_cases.csv",
        [{"id": "AT-01", "title": "t", "pytest_path": "tests/t.py::t", "test_type": "acceptance", "status": "passing"}],
    )

    return trace_dir


@pytest.fixture()
def tests_dir_with_dc_direct(tmp_path: Path) -> Path:
    """Tests directory where a test docstring has a direct DC-NNN reference."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")

    (tests / "test_direct_dc.py").write_text(
        textwrap.dedent('''\
            """Direct DC reference tests."""


            def test_wf01():
                """WF-01: DC-001. Directly references a design contract.

                This test explicitly verifies DC-001.
                """
                pass
        ''')
    )

    return tests


@pytest.fixture()
def tests_dir_with_unresolvable_req(tmp_path: Path) -> Path:
    """Tests directory where a test references a REQ not in fulfilled_by chain."""
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")

    (tests / "test_orphan_req.py").write_text(
        textwrap.dedent('''\
            """Tests referencing an unresolvable requirement."""


            def test_at01():
                """AT-01: REQ-999. References a REQ with no DC.

                REQ-999 does not exist in the fulfilled_by mapping.
                """
                pass
        ''')
    )

    return tests


# ---------------------------------------------------------------------------
# Marker: edge_generator
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.edge_generator


# ===========================================================================
# EDGE-REQ-001 through EDGE-REQ-005: Input file acceptance
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_001_accepts_design_contracts_csv(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-001: Generator MUST accept design_contracts.csv for fulfilled_by derivation.

    Verifies that the generator reads design_contracts.csv and uses it
    as the source for REQ→DC edge derivation.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    assert result.fulfilled_by_edges is not None
    assert len(result.fulfilled_by_edges) > 0


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_002_accepts_test_files_and_test_cases_csv(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-002: Generator MUST accept test source files and test_cases.csv for verified_by.

    Verifies that both inputs are consumed to derive DC→TC edges.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    assert result.verified_by_edges is not None


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_003_accepts_requirements_csv_for_validation(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-003: Generator MUST accept requirements.csv to validate referenced REQ IDs.

    Verifies the generator uses requirements.csv as the authoritative set
    of valid requirement IDs.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    # If requirements.csv is unreadable the generator must fail, not silently skip
    (traceability_dir / "requirements.csv").unlink()

    with pytest.raises(Exception):
        generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_004_accepts_design_contracts_csv_for_validation(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-004: Generator MUST accept design_contracts.csv to validate DC IDs.

    Verifies the generator uses design_contracts.csv as the authoritative
    set of valid design contract IDs.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    (traceability_dir / "design_contracts.csv").unlink()

    with pytest.raises(Exception):
        generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_005_accepts_test_cases_csv_for_validation(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-005: Generator MUST accept test_cases.csv to validate TC IDs.

    Verifies the generator uses test_cases.csv as the authoritative set
    of valid test case IDs.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    (traceability_dir / "test_cases.csv").unlink()

    with pytest.raises(Exception):
        generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)


# ===========================================================================
# EDGE-REQ-010: Source of REQ→DC references
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_010_derives_fulfilled_by_from_dc_text_fields(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-010: Generator MUST derive fulfilled_by edges from REQ-NNN in DC text fields.

    Pattern REQ-\\d{3} must be matched in any text field of a design contract row
    (guarantees, error_semantics, inputs, outputs).
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    req_ids = {e["requirement_id"] for e in result.fulfilled_by_edges}
    dc_ids = {e["design_contract_id"] for e in result.fulfilled_by_edges}

    # DC-001 has REQ-001, REQ-002, REQ-003 in guarantees/error_semantics
    assert "REQ-001" in req_ids
    assert "REQ-002" in req_ids
    assert "REQ-003" in req_ids
    assert "DC-001" in dc_ids


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_010_req_pattern_matched_in_all_text_fields(tmp_path: Path) -> None:
    """EDGE-REQ-010: REQ-NNN pattern matched in inputs, outputs, guarantees, error_semantics.

    Each DC text field is scanned — not just guarantees.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    trace_dir = tmp_path / "traceability"
    trace_dir.mkdir()

    _write_csv(
        trace_dir / "requirements.csv",
        [
            {"id": "REQ-001", "title": "R1", "description": "d", "priority": "high", "status": "draft", "source": "s"},
            {"id": "REQ-002", "title": "R2", "description": "d", "priority": "high", "status": "draft", "source": "s"},
            {"id": "REQ-003", "title": "R3", "description": "d", "priority": "high", "status": "draft", "source": "s"},
            {"id": "REQ-004", "title": "R4", "description": "d", "priority": "high", "status": "draft", "source": "s"},
        ],
    )

    _write_csv(
        trace_dir / "design_contracts.csv",
        [
            {
                "id": "DC-001",
                "title": "Multi",
                "module": "m.py",
                "inputs": "REQ-001",
                "outputs": "REQ-002",
                "guarantees": "REQ-003",
                "error_semantics": "REQ-004",
                "status": "draft",
            },
        ],
    )

    _write_csv(
        trace_dir / "test_cases.csv",
        [{"id": "AT-01", "title": "t", "pytest_path": "t.py::t", "test_type": "acceptance", "status": "passing"}],
    )

    tests_subdir = tmp_path / "tests"
    tests_subdir.mkdir()

    result = generate_edges(traceability_dir=trace_dir, tests_dir=tests_subdir)

    req_ids = {e["requirement_id"] for e in result.fulfilled_by_edges}
    assert {"REQ-001", "REQ-002", "REQ-003", "REQ-004"} == req_ids


# ===========================================================================
# EDGE-REQ-011: Alternative source — module docstrings (SHOULD)
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_011_scans_module_docstrings_for_req_refs(traceability_dir: Path, src_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-011: Generator SHOULD scan implementation module docstrings for REQ-NNN.

    References in a module docstring are associated with the DC whose module
    field matches that source file path.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, src_dir=src_dir)

    req_ids = {e["requirement_id"] for e in result.fulfilled_by_edges}
    # dispatcher.py docstring references REQ-001 → DC-001
    # transport.py docstring references REQ-004 → DC-002
    assert "REQ-001" in req_ids
    assert "REQ-004" in req_ids


# ===========================================================================
# EDGE-REQ-012: Completeness — full vs partial
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_012_completeness_full_when_single_dc(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-012: completeness MUST be 'full' when REQ is referenced by exactly one DC.

    REQ-001 appears only in DC-001 → completeness = full.
    REQ-003 appears only in DC-001 → completeness = full.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    by_req: dict[str, list[dict[str, str]]] = {}
    for edge in result.fulfilled_by_edges:
        by_req.setdefault(edge["requirement_id"], []).append(edge)

    assert by_req["REQ-001"][0]["completeness"] == "full"
    assert by_req["REQ-003"][0]["completeness"] == "full"


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_012_completeness_partial_when_multiple_dcs(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-012: completeness MUST be 'partial' when REQ is referenced by multiple DCs.

    REQ-002 appears in DC-001 (guarantees) and DC-002 (guarantees) → partial.
    REQ-004 appears only in DC-002 → full (control case).
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    by_req: dict[str, list[dict[str, str]]] = {}
    for edge in result.fulfilled_by_edges:
        by_req.setdefault(edge["requirement_id"], []).append(edge)

    # REQ-002 should appear twice with partial
    assert len(by_req["REQ-002"]) == 2
    assert all(e["completeness"] == "partial" for e in by_req["REQ-002"])

    # REQ-004 appears only in DC-002 → full
    assert by_req["REQ-004"][0]["completeness"] == "full"


# ===========================================================================
# EDGE-REQ-013: One edge per REQ-DC pair — no duplicates
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_013_no_duplicate_req_dc_edges(traceability_dir_duplicate_ref: Path, tests_dir: Path) -> None:
    """EDGE-REQ-013: Generator MUST NOT produce duplicate (REQ, DC) edges.

    When REQ-001 appears twice in different fields of DC-001, only one edge
    is produced.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir_duplicate_ref, tests_dir=tests_dir)

    pairs = [(e["requirement_id"], e["design_contract_id"]) for e in result.fulfilled_by_edges]
    assert len(pairs) == len(set(pairs)), "Duplicate (REQ, DC) pairs found in fulfilled_by output"


# ===========================================================================
# EDGE-REQ-020: Source of DC→TC references — test docstrings
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_020_derives_verified_by_from_test_docstrings(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-020: Generator MUST derive verified_by edges from test function docstrings.

    Each test docstring contains a TC ID (AT|WF|ST|ER|CP|SEC|API)-\\d{2}
    and REQ-NNN references.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    tc_ids = {e["test_case_id"] for e in result.verified_by_edges}
    assert "AT-01" in tc_ids
    assert "WF-01" in tc_ids


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_020_tc_pattern_matches_all_prefixes(tmp_path: Path) -> None:
    """EDGE-REQ-020: TC ID pattern must match AT, WF, ST, ER, CP, SEC, API prefixes.

    All six prefix types are valid test case ID patterns.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    trace_dir = tmp_path / "traceability"
    trace_dir.mkdir()

    _write_csv(
        trace_dir / "requirements.csv",
        [{"id": "REQ-001", "title": "R1", "description": "d", "priority": "high", "status": "draft", "source": "s"}],
    )
    _write_csv(
        trace_dir / "design_contracts.csv",
        [
            {
                "id": "DC-001",
                "title": "D1",
                "module": "m.py",
                "inputs": "",
                "outputs": "",
                "guarantees": "REQ-001",
                "error_semantics": "",
                "status": "draft",
            }
        ],
    )
    _write_csv(
        trace_dir / "test_cases.csv",
        [
            {"id": "AT-01", "title": "t", "pytest_path": "t.py::t", "test_type": "acceptance", "status": "passing"},
            {"id": "WF-01", "title": "t", "pytest_path": "t.py::t", "test_type": "wire_format", "status": "passing"},
            {"id": "ST-01", "title": "t", "pytest_path": "t.py::t", "test_type": "state", "status": "passing"},
            {"id": "ER-01", "title": "t", "pytest_path": "t.py::t", "test_type": "error", "status": "passing"},
            {"id": "CP-01", "title": "t", "pytest_path": "t.py::t", "test_type": "capability", "status": "passing"},
            {"id": "SEC-01", "title": "t", "pytest_path": "t.py::t", "test_type": "security", "status": "passing"},
            {"id": "API-01", "title": "t", "pytest_path": "t.py::t", "test_type": "api", "status": "passing"},
        ],
    )

    tests_subdir = tmp_path / "tests"
    tests_subdir.mkdir()
    (tests_subdir / "test_all_types.py").write_text(
        textwrap.dedent('''\
            def test_at01():
                """AT-01: REQ-001. Acceptance test."""
                pass
            def test_wf01():
                """WF-01: REQ-001. Wire format test."""
                pass
            def test_st01():
                """ST-01: REQ-001. State test."""
                pass
            def test_er01():
                """ER-01: REQ-001. Error model test."""
                pass
            def test_cp01():
                """CP-01: REQ-001. Capability test."""
                pass
            def test_sec01():
                """SEC-01: REQ-001. Security test."""
                pass
            def test_api01():
                """API-01: REQ-001. API test."""
                pass
        ''')
    )

    result = generate_edges(traceability_dir=trace_dir, tests_dir=tests_subdir)

    tc_ids = {e["test_case_id"] for e in result.verified_by_edges}
    assert {"AT-01", "WF-01", "ST-01", "ER-01", "CP-01", "SEC-01", "API-01"} == tc_ids


# ===========================================================================
# EDGE-REQ-021: DC assignment via requirement chain
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_021_dc_determined_via_requirement_chain(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-021: Generator MUST follow REQ chain to determine which DC a test verifies.

    test AT-01 references REQ-001 → fulfilled_by says REQ-001→DC-001
    → therefore AT-01 verifies DC-001.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    at01_edges = [e for e in result.verified_by_edges if e["test_case_id"] == "AT-01"]
    dc_ids = {e["design_contract_id"] for e in at01_edges}

    assert "DC-001" in dc_ids


# ===========================================================================
# EDGE-REQ-022: Direct DC references in test docstrings (SHOULD)
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_022_direct_dc_reference_in_docstring(traceability_dir: Path, tests_dir_with_dc_direct: Path) -> None:
    """EDGE-REQ-022: Generator SHOULD recognise direct DC-NNN references in test docstrings.

    A test docstring containing 'DC-001' directly produces a verified_by edge
    for that DC without going through the REQ chain.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir_with_dc_direct)

    wf01_edges = [e for e in result.verified_by_edges if e["test_case_id"] == "WF-01"]
    dc_ids = {e["design_contract_id"] for e in wf01_edges}

    assert "DC-001" in dc_ids


# ===========================================================================
# EDGE-REQ-023: Coverage — full vs partial
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_023_coverage_full_when_all_reqs_in_one_dc(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-023: coverage MUST be 'full' when test's REQs are all in the same single DC.

    AT-01 references REQ-001 which maps only to DC-001 → coverage = full.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    at01_edges = [e for e in result.verified_by_edges if e["test_case_id"] == "AT-01"]
    assert len(at01_edges) == 1
    assert at01_edges[0]["coverage"] == "full"


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_023_coverage_partial_when_reqs_span_multiple_dcs(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-023: coverage MUST be 'partial' when test's REQs span multiple DCs.

    WF-01 references REQ-002 which maps to both DC-001 and DC-002 → partial.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    wf01_edges = [e for e in result.verified_by_edges if e["test_case_id"] == "WF-01"]
    assert len(wf01_edges) >= 2
    assert all(e["coverage"] == "partial" for e in wf01_edges)


# ===========================================================================
# EDGE-REQ-024: One edge per DC-TC pair
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_024_no_duplicate_dc_tc_edges(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-024: Generator MUST NOT produce duplicate (DC, TC) pairs in verified_by.

    Even if a test references the same REQ multiple times, only one DC→TC edge
    is produced per unique pair.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    pairs = [(e["design_contract_id"], e["test_case_id"]) for e in result.verified_by_edges]
    assert len(pairs) == len(set(pairs)), "Duplicate (DC, TC) pairs found in verified_by output"


# ===========================================================================
# EDGE-REQ-030: fulfilled_by.csv format
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_030_fulfilled_by_csv_columns(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-030: fulfilled_by.csv MUST have columns requirement_id, design_contract_id, completeness.

    Output file must include a header row with exactly those three columns.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out_dir)

    fulfilled_by = out_dir / "fulfilled_by.csv"
    assert fulfilled_by.exists()

    rows = _read_csv(fulfilled_by)
    assert rows[0].keys() == {"requirement_id", "design_contract_id", "completeness"}


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_030_fulfilled_by_has_header_row(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-030: fulfilled_by.csv MUST include a header row.

    The first line of the file must be the column names.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out_dir)

    first_line = (out_dir / "fulfilled_by.csv").open().readline().strip()
    assert first_line == "requirement_id,design_contract_id,completeness"


# ===========================================================================
# EDGE-REQ-031: verified_by.csv format
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_031_verified_by_csv_columns(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-031: verified_by.csv MUST have columns design_contract_id, test_case_id, coverage.

    Output file must include a header row with exactly those three columns.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out_dir)

    verified_by = out_dir / "verified_by.csv"
    assert verified_by.exists()

    rows = _read_csv(verified_by)
    assert rows[0].keys() == {"design_contract_id", "test_case_id", "coverage"}


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_031_verified_by_has_header_row(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-031: verified_by.csv MUST include a header row.

    The first line of the file must be the column names.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out_dir)

    first_line = (out_dir / "verified_by.csv").open().readline().strip()
    assert first_line == "design_contract_id,test_case_id,coverage"


# ===========================================================================
# EDGE-REQ-032: Deterministic ordering
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_032_fulfilled_by_sorted_by_req_then_dc(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-032: fulfilled_by.csv rows MUST be sorted by requirement_id then design_contract_id.

    Deterministic ordering ensures stable diff-based review.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out_dir)

    rows = _read_csv(out_dir / "fulfilled_by.csv")
    pairs = [(r["requirement_id"], r["design_contract_id"]) for r in rows]

    assert pairs == sorted(pairs), "fulfilled_by.csv rows are not sorted"


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_032_verified_by_sorted_by_dc_then_tc(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-032: verified_by.csv rows MUST be sorted by design_contract_id then test_case_id.

    Deterministic ordering ensures stable diff-based review.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out_dir)

    rows = _read_csv(out_dir / "verified_by.csv")
    pairs = [(r["design_contract_id"], r["test_case_id"]) for r in rows]

    assert pairs == sorted(pairs), "verified_by.csv rows are not sorted"


# ===========================================================================
# EDGE-REQ-033: Idempotent output
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_033_output_is_idempotent(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-033: Running the generator twice on the same inputs produces identical output.

    Both CSV files must be byte-for-byte identical across two runs.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    out1.mkdir()
    out2.mkdir()

    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out1)
    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out2)

    assert (out1 / "fulfilled_by.csv").read_bytes() == (out2 / "fulfilled_by.csv").read_bytes()
    assert (out1 / "verified_by.csv").read_bytes() == (out2 / "verified_by.csv").read_bytes()


# ===========================================================================
# EDGE-REQ-040 through EDGE-REQ-042: Referential integrity validation
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_040_phantom_req_fails(traceability_dir_phantom_req: Path, tests_dir: Path) -> None:
    """EDGE-REQ-040: Generator MUST report and fail on phantom requirement references.

    REQ-999 does not exist in requirements.csv. The generator must raise
    an error or return a failure result, not silently produce the edge.
    """
    from v_model_traceability.generate_edges import GeneratorError, generate_edges  # type: ignore[import]

    with pytest.raises(GeneratorError):
        generate_edges(traceability_dir=traceability_dir_phantom_req, tests_dir=tests_dir)


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_040_phantom_req_not_in_output(traceability_dir_phantom_req: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-040: Phantom REQ must not appear in fulfilled_by output.

    If the generator produces partial output before failing, REQ-999
    must not be present in fulfilled_by.csv.
    """
    from v_model_traceability.generate_edges import GeneratorError, generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    try:
        generate_edges(traceability_dir=traceability_dir_phantom_req, tests_dir=tests_dir, output_dir=out_dir)
    except GeneratorError:
        pass

    fulfilled_by = out_dir / "fulfilled_by.csv"
    if fulfilled_by.exists():
        rows = _read_csv(fulfilled_by)
        assert all(r["requirement_id"] != "REQ-999" for r in rows)


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_041_phantom_dc_in_verified_by_fails(traceability_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-041: Generator MUST report and fail when verified_by references unknown DC.

    A test docstring referencing DC-999 (not in design_contracts.csv) triggers failure.
    """
    from v_model_traceability.generate_edges import GeneratorError, generate_edges  # type: ignore[import]

    tests_subdir = tmp_path / "tests"
    tests_subdir.mkdir()
    (tests_subdir / "test_phantom_dc.py").write_text(
        textwrap.dedent('''\
            def test_x():
                """AT-01: DC-999. Direct reference to non-existent DC."""
                pass
        ''')
    )

    with pytest.raises(GeneratorError):
        generate_edges(traceability_dir=traceability_dir, tests_dir=tests_subdir)


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_042_phantom_tc_in_verified_by_fails(traceability_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-042: Generator MUST fail when verified_by references a TC not in test_cases.csv.

    A docstring with a TC ID (XX-99) not in test_cases.csv triggers failure.
    """
    from v_model_traceability.generate_edges import GeneratorError, generate_edges  # type: ignore[import]

    tests_subdir = tmp_path / "tests"
    tests_subdir.mkdir()
    (tests_subdir / "test_phantom_tc.py").write_text(
        textwrap.dedent('''\
            def test_phantom():
                """AT-99: REQ-001. TC ID not registered in test_cases.csv."""
                pass
        ''')
    )

    with pytest.raises(GeneratorError):
        generate_edges(traceability_dir=traceability_dir, tests_dir=tests_subdir)


# ===========================================================================
# EDGE-REQ-043 and EDGE-REQ-044: Orphan detection warnings (SHOULD)
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_043_warns_on_req_without_dc(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-043: Generator SHOULD warn (not fail) when a REQ has no fulfilled_by edge.

    REQ-001 through REQ-004 are defined; not all are referenced in DC text.
    The generator must not raise on missing coverage, but should warn.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    # Must not raise
    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    # Any REQs without DC references should appear in result.warnings, not cause a raise.
    # The result must be returned (not raised) even with orphans.
    assert result is not None


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_044_warns_on_dc_without_tc(traceability_dir: Path, tests_dir: Path) -> None:
    """EDGE-REQ-044: Generator SHOULD warn (not fail) when a DC has no verified_by edge.

    Some DCs may have no test coverage. Generator must warn, not fail.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir)

    assert result is not None


# ===========================================================================
# EDGE-REQ-050 and EDGE-REQ-051: Golden dataset validation
# ===========================================================================


@pytest.mark.skipif(
    not TESSERON_TRACEABILITY.exists(),
    reason="python-tesseron repository not available",
)
@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_050_golden_fulfilled_by_matches_hand_written() -> None:
    """EDGE-REQ-050: Generator output MUST match python-tesseron hand-written fulfilled_by.csv.

    This is the primary golden dataset test. The generator is run against
    the full python-tesseron traceability data. The result must exactly
    reproduce the 120 hand-written edges (115 data rows + header).

    Deviations require individual justification and review.
    """
    import tempfile

    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    golden = _read_csv(TESSERON_TRACEABILITY / "fulfilled_by.csv")
    golden_pairs = {(r["requirement_id"], r["design_contract_id"]): r["completeness"] for r in golden}

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        generate_edges(
            traceability_dir=TESSERON_TRACEABILITY,
            tests_dir=TESSERON_TESTS,
            src_dir=TESSERON_SRC,
            output_dir=out_dir,
        )

        generated = _read_csv(out_dir / "fulfilled_by.csv")

    generated_pairs = {(r["requirement_id"], r["design_contract_id"]): r["completeness"] for r in generated}

    missing = set(golden_pairs.keys()) - set(generated_pairs.keys())
    extra = set(generated_pairs.keys()) - set(golden_pairs.keys())
    completeness_mismatches = {
        k: (golden_pairs[k], generated_pairs[k])
        for k in golden_pairs.keys() & generated_pairs.keys()
        if golden_pairs[k] != generated_pairs[k]
    }

    assert not missing, f"Edges in golden but missing from generated: {sorted(missing)}"
    assert not extra, f"Extra edges generated not in golden: {sorted(extra)}"
    assert not completeness_mismatches, f"Completeness mismatches: {completeness_mismatches}"


@pytest.mark.skipif(
    not TESSERON_TRACEABILITY.exists(),
    reason="python-tesseron repository not available",
)
@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_050_golden_verified_by_matches_hand_written() -> None:
    """EDGE-REQ-050: Generator output MUST match python-tesseron hand-written verified_by.csv.

    The generator is run against the full python-tesseron traceability data.
    The result must exactly reproduce the 157 hand-written verified_by edges.
    """
    import tempfile

    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    golden = _read_csv(TESSERON_TRACEABILITY / "verified_by.csv")
    golden_pairs = {(r["design_contract_id"], r["test_case_id"]): r["coverage"] for r in golden}

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        generate_edges(
            traceability_dir=TESSERON_TRACEABILITY,
            tests_dir=TESSERON_TESTS,
            src_dir=TESSERON_SRC,
            output_dir=out_dir,
        )

        generated = _read_csv(out_dir / "verified_by.csv")

    generated_pairs = {(r["design_contract_id"], r["test_case_id"]): r["coverage"] for r in generated}

    missing = set(golden_pairs.keys()) - set(generated_pairs.keys())
    extra = set(generated_pairs.keys()) - set(golden_pairs.keys())
    coverage_mismatches = {
        k: (golden_pairs[k], generated_pairs[k])
        for k in golden_pairs.keys() & generated_pairs.keys()
        if golden_pairs[k] != generated_pairs[k]
    }

    assert not missing, f"Edges in golden but missing from generated: {sorted(missing)}"
    assert not extra, f"Extra edges generated not in golden: {sorted(extra)}"
    assert not coverage_mismatches, f"Coverage mismatches: {coverage_mismatches}"


@pytest.mark.skipif(
    not TESSERON_TRACEABILITY.exists(),
    reason="python-tesseron repository not available",
)
@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_051_regression_test_runs_and_compares(tmp_path: Path) -> None:
    """EDGE-REQ-051: Test suite MUST include a regression test against python-tesseron data.

    This test IS that regression test. It runs the generator end-to-end against
    the committed python-tesseron traceability files and performs a byte-level
    comparison of both output CSVs against the committed golden files.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    generate_edges(
        traceability_dir=TESSERON_TRACEABILITY,
        tests_dir=TESSERON_TESTS,
        src_dir=TESSERON_SRC,
        output_dir=out_dir,
    )

    # Byte-level comparison — exact match required
    golden_fulfilled = (TESSERON_TRACEABILITY / "fulfilled_by.csv").read_bytes()
    golden_verified = (TESSERON_TRACEABILITY / "verified_by.csv").read_bytes()

    generated_fulfilled = (out_dir / "fulfilled_by.csv").read_bytes()
    generated_verified = (out_dir / "verified_by.csv").read_bytes()

    assert generated_fulfilled == golden_fulfilled, "fulfilled_by.csv does not match golden dataset"
    assert generated_verified == golden_verified, "verified_by.csv does not match golden dataset"


# ===========================================================================
# EDGE-REQ-060 through EDGE-REQ-062: CLI interface
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_060_cli_invocable_as_module(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-060: Generator MUST be invocable as python -m v_model_traceability.generate_edges.

    The CLI must accept <traceability_dir> positional argument.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "v_model_traceability.generate_edges",
            str(traceability_dir),
            "--tests-dir",
            str(tests_dir),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
    assert (out_dir / "fulfilled_by.csv").exists()
    assert (out_dir / "verified_by.csv").exists()


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_061_exit_code_0_on_success(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-061: Generator MUST exit 0 on success."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "v_model_traceability.generate_edges",
            str(traceability_dir),
            "--tests-dir",
            str(tests_dir),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_061_exit_code_1_on_validation_failure(
    traceability_dir_phantom_req: Path, tests_dir: Path, tmp_path: Path
) -> None:
    """EDGE-REQ-061: Generator MUST exit 1 on validation failure (phantom REQ reference).

    The exit code must be exactly 1, not 2 (missing files) or other non-zero.
    The error output must mention the offending phantom ID so the user can act on it.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "v_model_traceability.generate_edges",
            str(traceability_dir_phantom_req),
            "--tests-dir",
            str(tests_dir),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    # Output must identify the phantom requirement — not just crash with ModuleNotFoundError
    combined = proc.stdout + proc.stderr
    assert "REQ-999" in combined, f"Expected phantom REQ-999 in error output, got: {combined!r}"


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_061_exit_code_2_on_missing_input_files(tmp_path: Path) -> None:
    """EDGE-REQ-061: Generator MUST exit 2 when input files are missing."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    tests_subdir = tmp_path / "tests"
    tests_subdir.mkdir()

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "v_model_traceability.generate_edges",
            str(empty_dir),
            "--tests-dir",
            str(tests_subdir),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_062_one_summary_line_on_success(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-062: Generator MUST produce exactly one summary line on success (quiet by default).

    Stdout should contain a single summary line, nothing more.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "v_model_traceability.generate_edges",
            str(traceability_dir),
            "--tests-dir",
            str(tests_dir),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    output_lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(output_lines) == 1, f"Expected 1 summary line, got {len(output_lines)}: {proc.stdout!r}"


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_062_one_error_line_on_failure(traceability_dir_phantom_req: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-062: Generator MUST produce one error line with details on failure.

    The error output must identify the failing ID (REQ-999) so the user can act on it.
    A raw Python traceback without useful message does not satisfy this requirement.
    """
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "v_model_traceability.generate_edges",
            str(traceability_dir_phantom_req),
            "--tests-dir",
            str(tests_dir),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 1
    # Error details appear on stderr or stdout — either is acceptable.
    # Must identify the specific failing ID, not just crash with a generic traceback.
    combined = proc.stdout + proc.stderr
    assert "REQ-999" in combined, f"Expected phantom REQ-999 in error output, got: {combined!r}"


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_062_verbose_flag_enables_detail(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-062: --verbose flag SHOULD enable detailed output including all generated edges."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    proc_quiet = subprocess.run(
        [
            sys.executable,
            "-m",
            "v_model_traceability.generate_edges",
            str(traceability_dir),
            "--tests-dir",
            str(tests_dir),
            "--output-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )

    out_dir2 = tmp_path / "out2"
    out_dir2.mkdir()

    proc_verbose = subprocess.run(
        [
            sys.executable,
            "-m",
            "v_model_traceability.generate_edges",
            str(traceability_dir),
            "--tests-dir",
            str(tests_dir),
            "--output-dir",
            str(out_dir2),
            "--verbose",
        ],
        capture_output=True,
        text=True,
    )

    # Verbose output must be longer than quiet output
    assert len(proc_verbose.stdout) > len(proc_quiet.stdout), "Verbose output should be longer than quiet output"


# ===========================================================================
# EDGE-REQ-070 through EDGE-REQ-073: Edge cases
# ===========================================================================


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_070_req_with_no_dc_not_in_output(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-070: A REQ with no DC reference MUST NOT appear in fulfilled_by output.

    REQ-001 has no DC reference in the traceability_dir_no_req_refs fixture.
    It must be absent from fulfilled_by.csv.

    Note: traceability_dir has REQ-001 referenced; we use a dedicated fixture.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    # Build a scenario where REQ-004 has no DC reference
    trace_dir = tmp_path / "traceability"
    trace_dir.mkdir()
    _write_csv(
        trace_dir / "requirements.csv",
        [
            {"id": "REQ-001", "title": "R1", "description": "d", "priority": "high", "status": "draft", "source": "s"},
            {"id": "REQ-004", "title": "R4", "description": "d", "priority": "low", "status": "draft", "source": "s"},
        ],
    )
    _write_csv(
        trace_dir / "design_contracts.csv",
        [
            {
                "id": "DC-001",
                "title": "D1",
                "module": "m.py",
                "inputs": "",
                "outputs": "",
                "guarantees": "REQ-001",
                "error_semantics": "",
                "status": "draft",
            }
        ],
    )
    _write_csv(
        trace_dir / "test_cases.csv",
        [{"id": "AT-01", "title": "t", "pytest_path": "t.py::t", "test_type": "acceptance", "status": "passing"}],
    )

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    tests_subdir = tmp_path / "tests"
    tests_subdir.mkdir()

    generate_edges(traceability_dir=trace_dir, tests_dir=tests_subdir, output_dir=out_dir)

    rows = _read_csv(out_dir / "fulfilled_by.csv")
    req_ids = {r["requirement_id"] for r in rows}

    assert "REQ-004" not in req_ids, "REQ-004 has no DC reference but appeared in fulfilled_by.csv"


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_071_test_with_unresolvable_req_no_verified_by_edge(
    traceability_dir: Path,
    tests_dir_with_unresolvable_req: Path,
    tmp_path: Path,
) -> None:
    """EDGE-REQ-071: Test referencing REQ with no fulfilled_by edge MUST NOT produce verified_by edge.

    REQ-999 has no DC mapping → no verified_by edge for the test referencing it.
    Generator must not fail (only warn).
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Should not raise even though REQ-999 has no mapping
    result = generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir_with_unresolvable_req, output_dir=out_dir)

    rows = _read_csv(out_dir / "verified_by.csv")
    tc_ids = {r["test_case_id"] for r in rows}

    # AT-01 references REQ-999 which has no fulfilled_by chain → must not appear
    assert "AT-01" not in tc_ids
    assert result is not None


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_072_dc_with_no_req_refs_not_in_fulfilled_by(
    traceability_dir_no_req_refs: Path,
    tests_dir: Path,
    tmp_path: Path,
) -> None:
    """EDGE-REQ-072: A DC with no parseable REQ references MUST NOT appear in fulfilled_by.

    DC-002 has no REQ-NNN patterns in any field → must be absent from fulfilled_by output.
    Generator SHOULD warn about this.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = generate_edges(traceability_dir=traceability_dir_no_req_refs, tests_dir=tests_dir, output_dir=out_dir)

    rows = _read_csv(out_dir / "fulfilled_by.csv")
    dc_ids = {r["design_contract_id"] for r in rows}

    assert "DC-002" not in dc_ids, "DC-002 has no REQ refs but appeared in fulfilled_by.csv"
    assert result is not None


@pytest.mark.xfail(reason="implementation pending")
def test_edge_req_073_no_self_referencing_edges(traceability_dir: Path, tests_dir: Path, tmp_path: Path) -> None:
    """EDGE-REQ-073: Generator MUST NOT produce edges where source equals target.

    Structurally impossible given node types, but must be guarded. Verify that
    no fulfilled_by row has requirement_id == design_contract_id, and no
    verified_by row has design_contract_id == test_case_id.
    """
    from v_model_traceability.generate_edges import generate_edges  # type: ignore[import]

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    generate_edges(traceability_dir=traceability_dir, tests_dir=tests_dir, output_dir=out_dir)

    fulfilled = _read_csv(out_dir / "fulfilled_by.csv")
    for row in fulfilled:
        assert row["requirement_id"] != row["design_contract_id"], f"Self-referencing fulfilled_by edge found: {row}"

    verified = _read_csv(out_dir / "verified_by.csv")
    for row in verified:
        assert row["design_contract_id"] != row["test_case_id"], f"Self-referencing verified_by edge found: {row}"
