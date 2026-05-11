"""Edge CSV generator for v-model traceability.

Derives fulfilled_by.csv (REQ→DC edges) and verified_by.csv (DC→TC edges)
from design contracts, test source files, and optionally implementation source files.

Requirements covered: EDGE-REQ-001 through EDGE-REQ-073.

CLI usage::

    python -m v_model_traceability.generate_edges <traceability_dir> \\
        [--tests-dir <path>] \\
        [--src-dir <path>] \\
        [--output-dir <path>] \\
        [--verbose]

Exit codes:
    0  success
    1  validation failure (phantom IDs, referential integrity errors)
    2  missing input files
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GeneratorError(Exception):
    """Raised when edge generation fails due to validation or referential integrity errors."""

    def __init__(self, message: str, offending_ids: list[str] | None = None) -> None:
        """Initialise with a human-readable message and optional offending IDs.

        Args:
            message: Human-readable description of the failure.
            offending_ids: List of IDs that triggered the error (e.g. phantom REQ IDs).
        """
        super().__init__(message)
        self.offending_ids: list[str] = offending_ids or []


class MissingInputFileError(Exception):
    """Raised when a required input CSV file is not found."""

    def __init__(self, path: Path) -> None:
        """Initialise with the path that was not found.

        Args:
            path: The path that was not found.
        """
        super().__init__(f"Required input file not found: {path}")
        self.path = path


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GeneratorResult:
    """Result returned by generate_edges().

    Attributes:
        fulfilled_by_edges: List of REQ→DC edge dicts with keys
            requirement_id, design_contract_id, completeness.
        verified_by_edges: List of DC→TC edge dicts with keys
            design_contract_id, test_case_id, coverage.
        warnings: Human-readable warning strings (orphan nodes, unresolvable refs).
    """

    fulfilled_by_edges: list[dict[str, str]] = field(default_factory=list)
    verified_by_edges: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_REQ_PATTERN = re.compile(r"REQ-\d{3}")
_TC_PATTERN = re.compile(r"\b(AT|WF|ST|ER|CP|SEC|API)-\d{2}\b")
_DC_PATTERN = re.compile(r"\bDC-\d{3}\b")

# Docstring first-line pattern: "TC-ID: ..." — TC ID appears at start of docstring
_DOC_TC_PATTERN = re.compile(r"^\s*((?:AT|WF|ST|ER|CP|SEC|API)-\d{2})\s*[:\.]")


# ---------------------------------------------------------------------------
# CSV I/O helpers
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV file and return rows as a list of dicts.

    Args:
        path: Path to the CSV file.

    Returns:
        List of row dicts.

    Raises:
        MissingInputFileError: If the file does not exist.
    """
    if not path.exists():
        raise MissingInputFileError(path)
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    """Write rows to a CSV file with the given fieldnames as header.

    Uses Unix line endings (``\\n``) regardless of platform to ensure
    consistent byte-level output across operating systems.

    Args:
        path: Destination path.
        fieldnames: Column names (defines header order).
        rows: Row dicts to write.
    """
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Fulfilled-by derivation (REQ→DC edges from DC text fields)
# ---------------------------------------------------------------------------

_DC_TEXT_FIELDS = ("inputs", "outputs", "guarantees", "error_semantics")


def _extract_req_refs_from_dc(dc_row: dict[str, str]) -> set[str]:
    """Extract all REQ-NNN references from the text fields of a DC row.

    Scans inputs, outputs, guarantees, and error_semantics.

    Args:
        dc_row: A row dict from design_contracts.csv.

    Returns:
        Set of REQ-NNN strings found in any text field.
    """
    refs: set[str] = set()
    for field_name in _DC_TEXT_FIELDS:
        text = dc_row.get(field_name, "")
        refs.update(_REQ_PATTERN.findall(text))
    return refs


def _derive_fulfilled_by(
    dc_rows: list[dict[str, str]],
    valid_req_ids: set[str],
    src_dir: Path | None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Derive fulfilled_by edges from design contract text fields.

    Also optionally scans module docstrings in src_dir for REQ references,
    associating them with DCs via the module field.

    Args:
        dc_rows: Rows from design_contracts.csv.
        valid_req_ids: Set of all valid requirement IDs from requirements.csv.
        src_dir: Optional path to the source directory to scan module docstrings.

    Returns:
        Tuple of (edges, warnings) where edges is a list of dicts and
        warnings is a list of human-readable warning strings.

    Raises:
        GeneratorError: If any DC text references a REQ not in valid_req_ids.
    """
    warnings: list[str] = []

    # Build index: dc_id → set of referenced REQ ids (from text fields)
    dc_to_reqs: dict[str, set[str]] = {}
    phantom_refs: list[tuple[str, str]] = []  # (dc_id, req_id)

    for dc_row in dc_rows:
        dc_id = dc_row["id"]
        refs = _extract_req_refs_from_dc(dc_row)

        for req_id in refs:
            if req_id not in valid_req_ids:
                phantom_refs.append((dc_id, req_id))

        dc_to_reqs[dc_id] = refs - {r for _, r in phantom_refs if _ == dc_id}

    if phantom_refs:
        offending = sorted({req_id for _, req_id in phantom_refs})
        details = ", ".join(f"{dc_id}→{req_id}" for dc_id, req_id in sorted(phantom_refs))
        raise GeneratorError(
            f"Phantom requirement references in design contracts: {details}",
            offending_ids=offending,
        )

    # Optionally scan module docstrings for additional REQ references
    if src_dir is not None:
        _augment_from_src_docstrings(dc_rows, dc_to_reqs, valid_req_ids, src_dir, warnings)

    # Build REQ→set-of-DCs mapping to determine completeness
    req_to_dcs: dict[str, set[str]] = {}
    for dc_id, reqs in dc_to_reqs.items():
        for req_id in reqs:
            req_to_dcs.setdefault(req_id, set()).add(dc_id)

    # Warn about REQs with no DC coverage
    for req_id in valid_req_ids:
        if req_id not in req_to_dcs:
            warnings.append(f"REQ {req_id} has no fulfilled_by edge (no DC references it)")

    # Warn about DCs with no REQ references
    for dc_row in dc_rows:
        dc_id = dc_row["id"]
        if not dc_to_reqs.get(dc_id):
            warnings.append(f"DC {dc_id} has no REQ-NNN references in any text field")

    # Build deduplicated edge list
    edges: list[dict[str, str]] = []
    for req_id, dc_ids in req_to_dcs.items():
        completeness = "full" if len(dc_ids) == 1 else "partial"
        for dc_id in sorted(dc_ids):
            edges.append(
                {
                    "requirement_id": req_id,
                    "design_contract_id": dc_id,
                    "completeness": completeness,
                }
            )

    # Sort by requirement_id then design_contract_id
    edges.sort(key=lambda e: (e["requirement_id"], e["design_contract_id"]))

    return edges, warnings


def _augment_from_src_docstrings(
    dc_rows: list[dict[str, str]],
    dc_to_reqs: dict[str, set[str]],
    valid_req_ids: set[str],
    src_dir: Path,
    warnings: list[str],
) -> None:
    """Scan source file module docstrings for REQ-NNN and add to dc_to_reqs.

    Associates references with the DC whose module field matches the source file path.
    The module field in the DC row is matched against the relative path suffix of
    the source file.

    Args:
        dc_rows: Rows from design_contracts.csv.
        dc_to_reqs: Mutable mapping dc_id → set of req_ids (augmented in place).
        valid_req_ids: Set of valid requirement IDs.
        src_dir: Root of source directory to scan.
        warnings: Mutable list to append warnings to.
    """
    # Build index: module path suffix → dc_id
    module_to_dc: dict[str, str] = {}
    for dc_row in dc_rows:
        module_path = dc_row.get("module", "")
        if module_path:
            module_to_dc[module_path] = dc_row["id"]

    for py_file in src_dir.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            warnings.append(f"Could not read source file: {py_file}")
            continue

        # Extract module-level docstring (first triple-quoted string)
        docstring = _extract_module_docstring(source)
        if not docstring:
            continue

        refs = set(_REQ_PATTERN.findall(docstring))
        if not refs:
            continue

        # Match this file against DC module fields by suffix
        matched_dc: str | None = None
        for module_path, dc_id in module_to_dc.items():
            # Check if the source file path ends with the module path
            try:
                rel = py_file.relative_to(src_dir)
            except ValueError:
                continue
            if str(rel) == module_path or str(rel).endswith(module_path):
                matched_dc = dc_id
                break

        if matched_dc is None:
            # Try matching by filename suffix
            for module_path, dc_id in module_to_dc.items():
                if py_file.name == Path(module_path).name:
                    matched_dc = dc_id
                    break

        if matched_dc is None:
            continue

        for req_id in refs:
            if req_id in valid_req_ids:
                dc_to_reqs.setdefault(matched_dc, set()).add(req_id)
            else:
                warnings.append(f"Module docstring in {py_file} references unknown REQ {req_id}")


def _extract_module_docstring(source: str) -> str:
    """Extract the module-level docstring from Python source text.

    Args:
        source: Python source code as a string.

    Returns:
        The docstring text, or empty string if none found.
    """
    # Simple regex approach: find first triple-quoted string at start of file
    # (ignoring leading whitespace/comments)
    stripped = source.lstrip()
    for quote in ('"""', "'''"):
        if stripped.startswith(quote):
            end_quote = stripped.find(quote, len(quote))
            if end_quote != -1:
                return stripped[len(quote) : end_quote]
    return ""


# ---------------------------------------------------------------------------
# Test docstring scanning
# ---------------------------------------------------------------------------


def _scan_test_files(tests_dir: Path) -> list[tuple[str, str, str]]:
    """Scan test source files for function docstrings containing TC and REQ/DC references.

    Each test function docstring is expected to begin with one of:
    - ``TC-ID: REQ-NNN. description``  (REQ-based reference)
    - ``TC-ID: DC-NNN. description``   (direct DC reference)

    Args:
        tests_dir: Root of the test directory to scan recursively.

    Returns:
        List of (tc_id, ref_type, ref_id) tuples where ref_type is "REQ" or "DC".
        Multiple refs from one docstring produce multiple tuples.
    """
    findings: list[tuple[str, str, str]] = []

    for py_file in tests_dir.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError:
            continue

        findings.extend(_extract_tc_refs_from_source(source))

    return findings


def _extract_tc_refs_from_source(source: str) -> list[tuple[str, str, str]]:
    """Extract TC→REQ and TC→DC references from Python source code.

    Parses function definitions and their docstrings. Handles both
    top-level and indented function definitions.

    The first line of a docstring is expected to have the form:
    ``TC-ID: REQ-NNN[, REQ-NNN, ...]. description`` or
    ``TC-ID: DC-NNN. description``

    Args:
        source: Python source code as a string.

    Returns:
        List of (tc_id, "REQ"|"DC", ref_id) tuples.
    """
    findings: list[tuple[str, str, str]] = []

    # Split source into lines for processing
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Look for function definitions
        if stripped.startswith("def "):
            # Find the docstring on the next non-empty line
            j = i + 1
            # Skip to function body — find the first string literal
            while j < len(lines):
                body_line = lines[j].strip()
                if body_line == "":
                    j += 1
                    continue
                # Check if it starts with a triple-quote docstring
                if body_line.startswith('"""') or body_line.startswith("'''"):
                    quote = body_line[:3]
                    # Collect the full docstring
                    docstring_lines = [body_line[3:]]
                    if body_line.count(quote) >= 2 and body_line[3:].rstrip().endswith(quote):
                        # Single-line docstring
                        doc_text = body_line[3:].rstrip()[: -len(quote)]
                    else:
                        k = j + 1
                        while k < len(lines):
                            docstring_lines.append(lines[k].strip())
                            if quote in lines[k]:
                                break
                            k += 1
                        doc_text = "\n".join(docstring_lines)
                        # Remove trailing closing quote
                        end_pos = doc_text.rfind(quote)
                        if end_pos >= 0:
                            doc_text = doc_text[:end_pos]

                    # Parse TC ID from the first non-empty line of the docstring
                    first_line = doc_text.strip().splitlines()[0] if doc_text.strip() else ""
                    tc_match = _DOC_TC_PATTERN.match(first_line)
                    if tc_match:
                        tc_id = tc_match.group(1)
                        # Extract all REQ references from the entire docstring
                        req_refs = _REQ_PATTERN.findall(doc_text)
                        # Extract all DC references from the entire docstring first line
                        dc_refs = _DC_PATTERN.findall(first_line)

                        for req_id in req_refs:
                            findings.append((tc_id, "REQ", req_id))
                        for dc_id in dc_refs:
                            findings.append((tc_id, "DC", dc_id))

                    break
                else:
                    break
        i += 1

    return findings


# ---------------------------------------------------------------------------
# Verified-by derivation (DC→TC edges)
# ---------------------------------------------------------------------------


def _derive_verified_by(
    tc_findings: list[tuple[str, str, str]],
    req_to_dcs: dict[str, list[str]],
    valid_tc_ids: set[str],
    valid_dc_ids: set[str],
    valid_req_ids: set[str],
) -> tuple[list[dict[str, str]], list[str]]:
    """Derive verified_by edges from test docstring findings.

    Validation is applied only to TC IDs that would produce actual edges.
    A TC ID found in a test docstring that references only unresolvable REQs
    (not in requirements.csv or not in fulfilled_by mapping) produces no edges
    and its registration is not validated.

    Args:
        tc_findings: List of (tc_id, "REQ"|"DC", ref_id) tuples from test scanning.
        req_to_dcs: Mapping from requirement_id to list of design_contract_ids
            (from fulfilled_by edges).
        valid_tc_ids: Set of registered test case IDs from test_cases.csv.
        valid_dc_ids: Set of valid design contract IDs from design_contracts.csv.
        valid_req_ids: Set of valid requirement IDs from requirements.csv.

    Returns:
        Tuple of (edges, warnings).

    Raises:
        GeneratorError: If a TC that would produce edges references an unknown DC,
            or if a TC ID that resolves to edges is not in test_cases.csv.
    """
    warnings: list[str] = []

    # Group findings by TC ID
    tc_to_req_refs: dict[str, set[str]] = {}
    tc_to_dc_refs: dict[str, set[str]] = {}

    for tc_id, ref_type, ref_id in tc_findings:
        if ref_type == "REQ":
            tc_to_req_refs.setdefault(tc_id, set()).add(ref_id)
        else:
            tc_to_dc_refs.setdefault(tc_id, set()).add(ref_id)

    # First pass: validate DC references (always validate, regardless of resolution)
    phantom_dcs: list[tuple[str, str]] = []
    for tc_id, dc_refs in tc_to_dc_refs.items():
        for dc_id in dc_refs:
            if dc_id not in valid_dc_ids:
                phantom_dcs.append((tc_id, dc_id))

    if phantom_dcs:
        details = ", ".join(f"{tc}→{dc}" for tc, dc in sorted(phantom_dcs))
        offending = sorted({dc for _, dc in phantom_dcs})
        raise GeneratorError(
            f"Phantom DC references in test docstrings: {details}",
            offending_ids=offending,
        )

    # For each TC, resolve REQ refs to DC refs via the fulfilled_by chain
    # and combine with direct DC refs
    edges_set: set[tuple[str, str]] = set()  # (dc_id, tc_id)
    tc_to_resolved_dcs: dict[str, set[str]] = {}

    for tc_id in set(tc_to_req_refs) | set(tc_to_dc_refs):
        resolved_dcs: set[str] = set()

        # From REQ refs → follow fulfilled_by chain
        req_refs = tc_to_req_refs.get(tc_id, set())
        for req_id in req_refs:
            if req_id not in valid_req_ids:
                # REQ not in requirements.csv at all — warn, skip
                warnings.append(f"Test {tc_id} references REQ {req_id} which is not in requirements.csv (skipping)")
                continue
            dcs = req_to_dcs.get(req_id)
            if dcs is None:
                # REQ exists but has no fulfilled_by edge — warn, skip
                warnings.append(f"Test {tc_id} references REQ {req_id} which has no fulfilled_by mapping (skipping)")
            else:
                resolved_dcs.update(dcs)

        # From direct DC refs
        direct_dcs = tc_to_dc_refs.get(tc_id, set())
        resolved_dcs.update(direct_dcs)

        if resolved_dcs:
            tc_to_resolved_dcs[tc_id] = resolved_dcs

    # Second pass: validate TC IDs only for TCs that would produce edges
    phantom_tcs: list[str] = []
    for tc_id in tc_to_resolved_dcs:
        if tc_id not in valid_tc_ids:
            if tc_id not in phantom_tcs:
                phantom_tcs.append(tc_id)

    if phantom_tcs:
        raise GeneratorError(
            f"Test case IDs not in test_cases.csv: {sorted(phantom_tcs)}",
            offending_ids=sorted(phantom_tcs),
        )

    # Determine coverage per TC: "full" if all DCs resolve to same single DC, else "partial"
    edges: list[dict[str, str]] = []
    for tc_id, dc_ids in tc_to_resolved_dcs.items():
        coverage = "full" if len(dc_ids) == 1 else "partial"
        for dc_id in sorted(dc_ids):
            pair = (dc_id, tc_id)
            if pair not in edges_set:
                edges_set.add(pair)
                edges.append(
                    {
                        "design_contract_id": dc_id,
                        "test_case_id": tc_id,
                        "coverage": coverage,
                    }
                )

    # Sort by design_contract_id then test_case_id
    edges.sort(key=lambda e: (e["design_contract_id"], e["test_case_id"]))

    # Warn about DCs with no test coverage
    for dc_id in sorted(valid_dc_ids):
        if not any(e["design_contract_id"] == dc_id for e in edges):
            warnings.append(f"DC {dc_id} has no verified_by edge (no test references it)")

    return edges, warnings


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def generate_edges(
    traceability_dir: Path,
    tests_dir: Path,
    src_dir: Path | None = None,
    output_dir: Path | None = None,
) -> GeneratorResult:
    """Generate fulfilled_by and verified_by edge CSVs.

    Reads design_contracts.csv, requirements.csv, and test_cases.csv from
    traceability_dir. Scans tests_dir recursively for test function docstrings.
    Optionally scans src_dir for module docstrings.

    If ``fulfilled_by.csv`` already exists in ``traceability_dir``, it is
    treated as a pre-authored authoritative edge set and used directly instead
    of re-deriving edges from DC text fields.  Likewise, if ``verified_by.csv``
    already exists in ``traceability_dir``, it is used directly instead of
    re-deriving edges from test docstrings.

    If output_dir is provided, writes fulfilled_by.csv and verified_by.csv there.

    Args:
        traceability_dir: Directory containing design_contracts.csv,
            requirements.csv, and test_cases.csv.
        tests_dir: Directory to scan recursively for test Python files.
        src_dir: Optional directory to scan for implementation module docstrings.
        output_dir: Optional directory to write output CSVs to.

    Returns:
        GeneratorResult with fulfilled_by_edges, verified_by_edges, and warnings.

    Raises:
        MissingInputFileError: If any required input CSV is not found.
        GeneratorError: If validation fails (phantom IDs, referential integrity).
    """
    # Load input CSVs (raises MissingInputFileError if absent)
    req_rows = _read_csv(traceability_dir / "requirements.csv")
    dc_rows = _read_csv(traceability_dir / "design_contracts.csv")
    tc_rows = _read_csv(traceability_dir / "test_cases.csv")

    valid_req_ids: set[str] = {r["id"] for r in req_rows}
    valid_dc_ids: set[str] = {r["id"] for r in dc_rows}
    valid_tc_ids: set[str] = {r["id"] for r in tc_rows}

    warnings: list[str] = []

    # fulfilled_by: use pre-authored file if present, otherwise derive from DC text fields
    pre_authored_fb = traceability_dir / "fulfilled_by.csv"
    if pre_authored_fb.exists():
        fulfilled_by_edges = _read_csv(pre_authored_fb)
    else:
        fulfilled_by_edges, fb_warnings = _derive_fulfilled_by(dc_rows, valid_req_ids, src_dir)
        warnings.extend(fb_warnings)

    # Build REQ→DC mapping from fulfilled_by edges for verified_by derivation
    req_to_dcs: dict[str, list[str]] = {}
    for edge in fulfilled_by_edges:
        req_to_dcs.setdefault(edge["requirement_id"], []).append(edge["design_contract_id"])

    # verified_by: use pre-authored file if present, otherwise derive from test docstrings
    pre_authored_vb = traceability_dir / "verified_by.csv"
    if pre_authored_vb.exists():
        verified_by_edges = _read_csv(pre_authored_vb)
    else:
        # Scan test files
        tc_findings = _scan_test_files(tests_dir)

        # Derive verified_by edges
        verified_by_edges, vb_warnings = _derive_verified_by(
            tc_findings,
            req_to_dcs,
            valid_tc_ids,
            valid_dc_ids,
            valid_req_ids,
        )
        warnings.extend(vb_warnings)

    # Write output if requested
    if output_dir is not None:
        _write_csv(
            output_dir / "fulfilled_by.csv",
            ["requirement_id", "design_contract_id", "completeness"],
            fulfilled_by_edges,
        )
        _write_csv(
            output_dir / "verified_by.csv",
            ["design_contract_id", "test_case_id", "coverage"],
            verified_by_edges,
        )

    return GeneratorResult(
        fulfilled_by_edges=fulfilled_by_edges,
        verified_by_edges=verified_by_edges,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m v_model_traceability.generate_edges",
        description="Generate fulfilled_by.csv and verified_by.csv edge files.",
    )
    parser.add_argument(
        "traceability_dir",
        type=Path,
        help="Directory containing design_contracts.csv, requirements.csv, test_cases.csv.",
    )
    parser.add_argument(
        "--tests-dir",
        type=Path,
        default=None,
        help="Directory to scan for test Python files.",
    )
    parser.add_argument(
        "--src-dir",
        type=Path,
        default=None,
        help="Directory to scan for implementation module docstrings.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write output CSVs to (defaults to traceability_dir).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed output including all generated edges.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the edge generator CLI.

    Args:
        argv: Command-line arguments (uses sys.argv if None).

    Returns:
        Exit code: 0 success, 1 validation failure, 2 missing input files.
    """
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    traceability_dir: Path = args.traceability_dir
    tests_dir: Path = args.tests_dir if args.tests_dir is not None else traceability_dir / "tests"
    src_dir: Path | None = args.src_dir
    output_dir: Path = args.output_dir if args.output_dir is not None else traceability_dir
    verbose: bool = args.verbose

    try:
        result = generate_edges(
            traceability_dir=traceability_dir,
            tests_dir=tests_dir,
            src_dir=src_dir,
            output_dir=output_dir,
        )
    except MissingInputFileError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except GeneratorError as exc:
        offending = ", ".join(exc.offending_ids) if exc.offending_ids else str(exc)
        print(f"ERROR: {exc} [{offending}]", file=sys.stderr)
        return 1

    fb_count = len(result.fulfilled_by_edges)
    vb_count = len(result.verified_by_edges)
    print(f"Generated {fb_count} fulfilled_by edges and {vb_count} verified_by edges.")

    if verbose:
        if result.warnings:
            for warning in result.warnings:
                print(f"  WARNING: {warning}")
        print("  fulfilled_by edges:")
        for edge in result.fulfilled_by_edges:
            print(f"    {edge['requirement_id']} -> {edge['design_contract_id']} ({edge['completeness']})")
        print("  verified_by edges:")
        for edge in result.verified_by_edges:
            print(f"    {edge['design_contract_id']} -> {edge['test_case_id']} ({edge['coverage']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
